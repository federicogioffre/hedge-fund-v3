"""
V6 Rebalancer.

Translates portfolio_engine targets into actual orders routed through the
execution engine. Enforces:

    - Rebalance threshold (skip trades below REBALANCE_THRESHOLD_PCT)
    - Fund-level risk guards (drawdown, daily loss, position caps)
    - Idempotent execution via client_order_id

Flow:
    rankings (latest AnalysisResult) -> construct_portfolio()
    -> target weights per ticker
    -> diff vs current positions
    -> pre-trade risk check
    -> ExecutionEngine.place_order()
    -> persist_fund_state()
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func

from app.config import get_settings
from app.data_sources import fetch_market_data
from app.db import get_db
from app.execution_engine import ExecutionEngine
from app.logging import get_logger
from app.models import AnalysisResult, Position
from app.portfolio_engine import construct_portfolio
from app.risk_guards import (
    check_pre_trade,
    compute_fund_state,
    persist_fund_state,
)

logger = get_logger(__name__)


def _load_latest_rankings(
    tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load most recent completed analysis per ticker."""
    with get_db() as session:
        subquery = (
            session.query(
                AnalysisResult.ticker,
                func.max(AnalysisResult.id).label("max_id"),
            )
            .filter(AnalysisResult.status == "completed")
            .group_by(AnalysisResult.ticker)
            .subquery()
        )

        query = session.query(AnalysisResult).join(
            subquery, AnalysisResult.id == subquery.c.max_id
        )
        if tickers:
            upper = [t.upper() for t in tickers]
            query = query.filter(AnalysisResult.ticker.in_(upper))

        records = query.all()

        rankings: list[dict[str, Any]] = []
        for r in records:
            agent_data = r.agent_results or []
            risks = [a.get("risk", 0.3) for a in agent_data]
            risk_score = (
                round(sum(risks) / len(risks), 3) if risks else 0.3
            )
            rankings.append(
                {
                    "ticker": r.ticker,
                    "overall_score": r.overall_score or 3.0,
                    "confidence": r.confidence or 0.5,
                    "conviction": r.conviction or 0.0,
                    "risk_score": risk_score,
                    "recommendation": r.recommendation or "hold",
                }
            )
        return rankings


def _current_positions_by_ticker(
    trading_mode: str,
) -> dict[str, Position]:
    """Snapshot of live positions keyed by ticker."""
    with get_db() as session:
        rows = (
            session.query(Position)
            .filter(Position.trading_mode == trading_mode)
            .all()
        )
        # Detach from session by copying primitive attrs we need
        return {
            row.ticker: {
                "ticker": row.ticker,
                "quantity": row.quantity,
                "avg_entry_price": row.avg_entry_price,
                "current_price": row.current_price,
                "market_value": row.market_value or 0.0,
            }
            for row in rows
        }


async def _resolve_price(ticker: str) -> float:
    market = await fetch_market_data(ticker, "equity")
    return float(market.get("price", 0.0))


async def rebalance(
    tickers: list[str] | None = None,
    capital: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Rebalance the fund toward portfolio_engine targets.

    Args:
        tickers: optional subset to rebalance (defaults to all with analysis)
        capital: override for target capital base (defaults to current equity)
        dry_run: if True, compute the diff but do not place orders

    Returns:
        dict with executed/skipped orders and a fresh fund_state snapshot.
    """
    settings = get_settings()
    trading_mode = settings.trading_mode
    engine = ExecutionEngine(trading_mode=trading_mode)

    # 1. Load fund state for capital base
    with get_db() as session:
        fund_snapshot = compute_fund_state(session, trading_mode)

    capital_base = (
        capital if capital is not None else fund_snapshot["equity"]
    )
    if capital_base <= 0:
        capital_base = settings.initial_capital

    # 2. Load latest rankings and build target portfolio
    rankings = _load_latest_rankings(tickers)
    if not rankings:
        return {
            "status": "no_rankings",
            "message": (
                "No completed analysis found. Run /analyze first."
            ),
            "executed": [],
            "skipped": [],
            "fund_state": fund_snapshot,
            "timestamp": datetime.utcnow().isoformat(),
        }

    target_portfolio = construct_portfolio(rankings, capital=capital_base)
    target_by_ticker: dict[str, dict[str, Any]] = {
        p["ticker"]: p for p in target_portfolio["positions"]
    }

    # 3. Snapshot current positions
    current = _current_positions_by_ticker(trading_mode)

    universe = set(target_by_ticker.keys()) | set(current.keys())
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    # 4. Compute and apply deltas per ticker
    for ticker in sorted(universe):
        target = target_by_ticker.get(ticker)
        target_notional = float(target["allocation"]) if target else 0.0

        current_pos = current.get(ticker)
        current_notional = (
            float(current_pos["market_value"]) if current_pos else 0.0
        )

        delta_notional = target_notional - current_notional
        delta_pct = (
            abs(delta_notional) / capital_base * 100
            if capital_base > 0
            else 0.0
        )

        if delta_pct < settings.rebalance_threshold_pct:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": "below_threshold",
                    "delta_pct": round(delta_pct, 3),
                    "target_notional": round(target_notional, 2),
                    "current_notional": round(current_notional, 2),
                }
            )
            continue

        side = "buy" if delta_notional > 0 else "sell"
        abs_notional = abs(delta_notional)

        # 5. Resolve current market price
        try:
            price = await _resolve_price(ticker)
        except Exception as e:
            logger.warning(
                "rebalance_price_error", ticker=ticker, error=str(e)
            )
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": f"price_error: {e}",
                    "delta_pct": round(delta_pct, 3),
                }
            )
            continue

        if price <= 0:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": "invalid_price",
                    "price": price,
                }
            )
            continue

        size = round(abs_notional / price, 6)
        if size <= 0:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": "zero_size",
                    "delta_notional": delta_notional,
                }
            )
            continue

        # For sells, don't exceed current quantity
        if side == "sell" and current_pos is not None:
            max_sell = float(current_pos["quantity"])
            if max_sell <= 0:
                skipped.append(
                    {
                        "ticker": ticker,
                        "reason": "no_position_to_sell",
                    }
                )
                continue
            size = min(size, round(max_sell, 6))
            abs_notional = round(size * price, 2)

        # 6. Risk pre-trade check
        decision = check_pre_trade(ticker, side, abs_notional)
        if not decision.allowed:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": decision.reason,
                    "guard": decision.guard,
                    "side": side,
                    "notional": round(abs_notional, 2),
                }
            )
            logger.warning(
                "rebalance_blocked",
                ticker=ticker,
                guard=decision.guard,
                reason=decision.reason,
            )
            continue

        if dry_run:
            executed.append(
                {
                    "ticker": ticker,
                    "side": side,
                    "size": size,
                    "notional": round(abs_notional, 2),
                    "dry_run": True,
                }
            )
            continue

        # 7. Place order
        try:
            order = await engine.place_order(
                ticker=ticker,
                side=side,  # type: ignore[arg-type]
                size=size,
                reference_price=price,
            )
            executed.append(
                {
                    "ticker": ticker,
                    "side": side,
                    "size": size,
                    "notional": round(abs_notional, 2),
                    "order": order,
                }
            )
        except Exception as e:
            logger.error(
                "rebalance_order_error", ticker=ticker, error=str(e)
            )
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": f"order_error: {e}",
                    "side": side,
                }
            )

    # 8. Mark to market and persist fresh fund state
    if not dry_run and executed:
        try:
            await engine.mark_to_market()
        except Exception as e:
            logger.warning("mtm_after_rebalance_error", error=str(e))

    fresh_state = persist_fund_state(trading_mode)

    result = {
        "status": "ok",
        "trading_mode": trading_mode,
        "capital_base": round(capital_base, 2),
        "target_portfolio": {
            "positions": target_portfolio["positions"],
            "total_allocated_pct": target_portfolio["total_allocated_pct"],
            "cash_pct": target_portfolio["cash_pct"],
        },
        "executed": executed,
        "skipped": skipped,
        "executed_count": len(executed),
        "skipped_count": len(skipped),
        "fund_state": fresh_state,
        "dry_run": dry_run,
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info(
        "rebalance_complete",
        executed=len(executed),
        skipped=len(skipped),
        equity=fresh_state["equity"],
        drawdown_pct=fresh_state["drawdown_pct"],
        dry_run=dry_run,
    )
    return result
