"""
LLM-backed Celery tasks (TradingAgents).

Runs on the dedicated `llm_slow` queue so the primary worker stays
responsive. Idempotent per (ticker, asset_type, TA_VERSION) via a Redis
in-flight lock; bounded concurrency via a Redis semaphore.
"""

from __future__ import annotations

import time
from typing import Any

from app.agents_llm.tradingagents_agent import (
    TA_VERSION,
    read_cached_ta,
    write_cached_ta,
)
from app.cache import get_redis
from app.celery_app import celery_app
from app.config import get_settings
from app.db import get_db
from app.logging import get_logger
from app.models import SignalHistory

logger = get_logger(__name__)

_INFLIGHT_PREFIX = "tradingagents:inflight"
_SEMAPHORE_KEY = "tradingagents:semaphore"
_INFLIGHT_TTL = 300  # 5 min max lock


def _inflight_key(ticker: str, asset_type: str) -> str:
    return f"{_INFLIGHT_PREFIX}:{ticker.upper()}:{asset_type}:{TA_VERSION}"


def _try_acquire_inflight(ticker: str, asset_type: str) -> bool:
    try:
        r = get_redis()
        return bool(r.set(_inflight_key(ticker, asset_type), "1",
                          nx=True, ex=_INFLIGHT_TTL))
    except Exception:
        return True  # fail-open: still run the task


def _release_inflight(ticker: str, asset_type: str) -> None:
    try:
        get_redis().delete(_inflight_key(ticker, asset_type))
    except Exception:
        pass


def _try_acquire_semaphore(limit: int) -> bool:
    """Best-effort concurrency cap using INCR with TTL."""
    try:
        r = get_redis()
        current = r.incr(_SEMAPHORE_KEY)
        if current == 1:
            r.expire(_SEMAPHORE_KEY, 600)
        if current > limit:
            r.decr(_SEMAPHORE_KEY)
            return False
        return True
    except Exception:
        return True


def _release_semaphore() -> None:
    try:
        r = get_redis()
        v = r.decr(_SEMAPHORE_KEY)
        if v is not None and v < 0:
            r.set(_SEMAPHORE_KEY, 0)
    except Exception:
        pass


def _mock_tradingagents_payload(
    ticker: str, asset_type: str, depth: int
) -> dict[str, Any]:
    """
    Deterministic mock output used when the real TradingAgents framework
    isn't installed or provider=mock. Good enough to smoke-test the
    integration end-to-end without burning tokens.
    """
    import hashlib

    seed = int(hashlib.md5(ticker.encode()).hexdigest()[:8], 16)
    decisions = ["strong_sell", "sell", "hold", "buy", "strong_buy"]
    decision = decisions[seed % len(decisions)]

    return {
        "decision": decision,
        "confidence": 0.55 + (seed % 30) / 100.0,  # 0.55..0.85
        "bull_arguments": [
            f"{ticker} has shown consistent momentum",
            f"{ticker} sector tailwinds favorable",
        ],
        "bear_arguments": [
            f"{ticker} valuation appears stretched",
        ],
        "risk_assessment": {
            "level": "medium",
            "notes": f"Position sizing recommended for {ticker}",
        },
        "trader_summary": (
            f"[MOCK] {decision.upper()} {ticker} ({asset_type}) — "
            f"depth={depth}. This is a synthetic TradingAgents output for "
            "integration testing."
        ),
        "transcript": (
            f"[MOCK debate transcript for {ticker}]\nRound 1: analysts aligned."
        ),
        "model": "mock-tradingagents",
    }


def _run_real_tradingagents(
    ticker: str,
    asset_type: str,
    provider: str,
    model: str,
    depth: int,
) -> dict[str, Any]:
    """
    Invoke the real TauricResearch/TradingAgents framework.

    The framework is an *optional* dependency — we import lazily and fall
    back to the mock if it isn't installed. When the package is present,
    we call its LangGraph entrypoint and normalize its output to our
    parser's expected shape.
    """
    try:
        # The public import path of the project. Adjust here if the
        # upstream API changes; the parser is tolerant to extra fields.
        from tradingagents.graph import TradingAgentsGraph  # type: ignore
    except Exception as e:  # pragma: no cover - optional dep
        logger.warning(
            "tradingagents_package_missing",
            error=str(e),
            fallback="mock",
        )
        return _mock_tradingagents_payload(ticker, asset_type, depth)

    try:
        graph = TradingAgentsGraph(  # type: ignore
            provider=provider,
            model=model,
            debate_rounds=depth,
        )
        raw = graph.run(ticker=ticker, asset_type=asset_type)
        if not isinstance(raw, dict):
            raw = {"decision": "hold", "raw": str(raw)}
        raw.setdefault("model", f"{provider}:{model}")
        return raw
    except Exception as e:
        logger.error(
            "tradingagents_run_error", ticker=ticker, error=str(e)
        )
        # Don't poison the cache with an error — let the next call retry
        raise


@celery_app.task(
    bind=True,
    name="app.tasks_llm.generate_tradingagents_signal",
    queue="llm_slow",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def generate_tradingagents_signal(
    self,
    ticker: str,
    asset_type: str = "equity",
) -> dict[str, Any]:
    """Generate and cache a TradingAgents signal for a ticker."""
    settings = get_settings()
    ticker = ticker.upper()

    # If a fresh entry was just produced, skip the work
    existing = read_cached_ta(ticker, asset_type)
    if existing:
        age = time.time() - float(existing.get("generated_at") or 0)
        if age < settings.tradingagents_cache_ttl:
            logger.info(
                "tradingagents_skip_fresh",
                ticker=ticker,
                age_s=round(age, 1),
            )
            return {"status": "skipped", "reason": "fresh", "age_s": age}

    # Idempotency: only one in-flight generation per ticker
    if not _try_acquire_inflight(ticker, asset_type):
        logger.info("tradingagents_skip_inflight", ticker=ticker)
        return {"status": "skipped", "reason": "inflight"}

    # Concurrency cap across the cluster
    if not _try_acquire_semaphore(settings.tradingagents_max_concurrent):
        _release_inflight(ticker, asset_type)
        logger.info("tradingagents_semaphore_full", ticker=ticker)
        # Retry with backoff
        raise self.retry(countdown=30, exc=RuntimeError("semaphore_full"))

    start = time.time()
    try:
        if settings.tradingagents_provider == "mock" or not settings.tradingagents_enabled:
            payload = _mock_tradingagents_payload(
                ticker, asset_type, settings.tradingagents_depth
            )
        else:
            payload = _run_real_tradingagents(
                ticker=ticker,
                asset_type=asset_type,
                provider=settings.tradingagents_provider,
                model=settings.tradingagents_model,
                depth=settings.tradingagents_depth,
            )

        write_cached_ta(ticker, asset_type, payload)

        # Persist a SignalHistory row (parsed) for audit / blending history
        try:
            from app.agents_llm.ta_parser import parse_tradingagents_output

            parsed = parse_tradingagents_output(payload)
            with get_db() as session:
                session.add(
                    SignalHistory(
                        ticker=ticker,
                        agent_name="tradingagents",
                        score=parsed["score"],
                        confidence=parsed["confidence"],
                        risk=parsed["risk"],
                        momentum=None,
                        acceleration=None,
                        request_id=None,
                    )
                )
        except Exception as e:
            logger.warning(
                "tradingagents_signal_history_error",
                ticker=ticker,
                error=str(e),
            )

        duration_ms = round((time.time() - start) * 1000, 1)
        logger.info(
            "tradingagents_generated",
            ticker=ticker,
            provider=settings.tradingagents_provider,
            model=settings.tradingagents_model,
            duration_ms=duration_ms,
        )
        return {
            "status": "ok",
            "ticker": ticker,
            "duration_ms": duration_ms,
        }
    finally:
        _release_semaphore()
        _release_inflight(ticker, asset_type)
