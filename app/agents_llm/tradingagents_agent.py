"""
TradingAgentsAgent: hedge-fund-v3 BaseAgent that wraps the
TauricResearch/TradingAgents framework as an LLM signal provider.

Strategy on the hot path (reads only):
    1. Look up Redis cache `tradingagents:{ticker}:{asset_type}:{TA_VERSION}`
    2. If fresh (< cache_ttl): parse → return AgentResult
    3. If stale (> cache_ttl but < stale_ttl): return parsed stale + enqueue
       Celery refresh in background (fire-and-forget)
    4. If missing or older than stale_ttl: return neutral fallback + enqueue
       refresh

The actual LLM call NEVER runs on the hot path — only in the dedicated
`llm_slow` Celery queue (app.tasks_llm.generate_tradingagents_signal).
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.agents import AgentResult, BaseAgent, FALLBACK_SCORE
from app.agents_llm.ta_parser import parse_tradingagents_output
from app.cache import get_redis
from app.config import get_settings
from app.data_bundle import DataBundle
from app.logging import get_logger

logger = get_logger(__name__)


# Bumped only when the parser or cache schema changes, not on LLM output
TA_VERSION = "ta_v1"


def ta_cache_key(ticker: str, asset_type: str) -> str:
    return f"tradingagents:{ticker.upper()}:{asset_type}:{TA_VERSION}"


def read_cached_ta(ticker: str, asset_type: str) -> dict[str, Any] | None:
    """Return {'payload': ..., 'generated_at': epoch} or None."""
    try:
        r = get_redis()
        raw = r.get(ta_cache_key(ticker, asset_type))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(
            "tradingagents_cache_read_error", ticker=ticker, error=str(e)
        )
        return None


def write_cached_ta(
    ticker: str, asset_type: str, payload: dict[str, Any]
) -> None:
    """Persist TradingAgents output under a stable cache key with TTL."""
    try:
        settings = get_settings()
        r = get_redis()
        envelope = {
            "payload": payload,
            "generated_at": time.time(),
            "ticker": ticker.upper(),
            "asset_type": asset_type,
        }
        # Use stale_ttl as Redis TTL so stale-but-usable entries survive
        r.setex(
            ta_cache_key(ticker, asset_type),
            settings.tradingagents_stale_ttl,
            json.dumps(envelope, default=str),
        )
    except Exception as e:
        logger.warning(
            "tradingagents_cache_write_error", ticker=ticker, error=str(e)
        )


def _enqueue_refresh(ticker: str, asset_type: str) -> None:
    """Fire-and-forget Celery task — never raise on the hot path."""
    try:
        # Imported lazily to avoid Celery import at module load time
        from app.tasks_llm import generate_tradingagents_signal

        generate_tradingagents_signal.delay(ticker, asset_type)
        logger.info(
            "tradingagents_refresh_enqueued",
            ticker=ticker,
            asset_type=asset_type,
        )
    except Exception as e:
        logger.warning(
            "tradingagents_refresh_enqueue_error",
            ticker=ticker,
            error=str(e),
        )


class TradingAgentsAgent(BaseAgent):
    """Hot-path agent: cache-only read; enqueue LLM work in background."""

    name = "tradingagents"

    def __init__(self) -> None:
        settings = get_settings()
        # Short timeout — we only hit Redis + parse
        self.timeout_s: float = float(settings.tradingagents_read_timeout_s)

    async def analyze(self, bundle: DataBundle) -> AgentResult:
        settings = get_settings()
        ticker = bundle.ticker.upper()
        asset_type = bundle.asset_type
        now = time.time()

        envelope = read_cached_ta(ticker, asset_type)

        if envelope is None:
            # Missing: neutral fallback + schedule a generation
            _enqueue_refresh(ticker, asset_type)
            return AgentResult(
                agent_name=self.name,
                score=FALLBACK_SCORE,
                confidence=0.25,
                risk=0.5,
                reasoning=(
                    "TradingAgents signal not yet available for this "
                    "ticker; generation enqueued."
                ),
                metadata={
                    "fallback": True,
                    "reason": "cache_miss",
                    "source": "tradingagents",
                },
            )

        generated_at = float(envelope.get("generated_at") or 0)
        age = now - generated_at
        payload = envelope.get("payload") or {}

        # Too old → treat as miss
        if age > settings.tradingagents_stale_ttl:
            _enqueue_refresh(ticker, asset_type)
            return AgentResult(
                agent_name=self.name,
                score=FALLBACK_SCORE,
                confidence=0.25,
                risk=0.5,
                reasoning=(
                    f"TradingAgents signal expired (age {int(age)}s); "
                    "refresh enqueued."
                ),
                metadata={
                    "fallback": True,
                    "reason": "cache_expired",
                    "age_s": round(age, 1),
                    "source": "tradingagents",
                },
            )

        kwargs = parse_tradingagents_output(payload)
        is_stale = age > settings.tradingagents_cache_ttl
        if is_stale:
            # Usable but past fresh TTL: schedule a refresh in the background
            _enqueue_refresh(ticker, asset_type)

        meta = kwargs.get("metadata", {}) or {}
        meta.update(
            {
                "age_s": round(age, 1),
                "stale": is_stale,
                "cache_ttl_s": settings.tradingagents_cache_ttl,
            }
        )
        kwargs["metadata"] = meta

        return AgentResult(**kwargs)
