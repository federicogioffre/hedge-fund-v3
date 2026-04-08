"""
V6 Fund-level Risk Guards.

Enforces:
    - max portfolio drawdown
    - max position size (%)
    - daily loss limit

If any guard triggers, `check_pre_trade` returns a rejection and the
execution engine will not submit the order. Fund-level state is persisted
in the `fund_state` table and updated after every trade.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.logging import get_logger
from app.models import FundState, Position

logger = get_logger(__name__)


@dataclass
class GuardDecision:
    allowed: bool
    reason: str | None = None
    guard: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "guard": self.guard,
        }


def get_or_create_fund_state(
    session: Session, trading_mode: str
) -> FundState:
    """Load the latest fund state row or create an initial one."""
    settings = get_settings()
    state = (
        session.query(FundState)
        .filter_by(trading_mode=trading_mode)
        .order_by(FundState.created_at.desc())
        .first()
    )
    if state is None:
        state = FundState(
            trading_mode=trading_mode,
            cash=settings.initial_capital,
            equity=settings.initial_capital,
            total_realized_pnl=0.0,
            total_unrealized_pnl=0.0,
            peak_equity=settings.initial_capital,
            drawdown_pct=0.0,
            daily_pnl=0.0,
            trading_halted=False,
        )
        session.add(state)
        session.flush()
    return state


def compute_fund_state(
    session: Session, trading_mode: str
) -> dict[str, Any]:
    """Compute current fund state from positions."""
    settings = get_settings()

    positions = (
        session.query(Position)
        .filter(
            Position.trading_mode == trading_mode,
            Position.quantity != 0,
        )
        .all()
    )

    total_market_value = sum(
        (p.market_value or 0.0) for p in positions
    )
    total_cost_basis = sum(p.cost_basis for p in positions)
    total_realized = sum(p.realized_pnl for p in positions)
    total_unrealized = sum(p.unrealized_pnl for p in positions)

    # Cash = initial capital + realized PnL - current cost basis of open positions
    cash = round(
        settings.initial_capital + total_realized - total_cost_basis, 2
    )
    equity = round(cash + total_market_value, 2)

    # Load latest for peak/daily tracking
    latest = (
        session.query(FundState)
        .filter_by(trading_mode=trading_mode)
        .order_by(FundState.created_at.desc())
        .first()
    )
    peak_equity = max(
        equity, (latest.peak_equity if latest else equity)
    )
    drawdown_pct = (
        round((peak_equity - equity) / peak_equity * 100, 3)
        if peak_equity > 0
        else 0.0
    )

    # Daily PnL: compare to earliest fund_state in the last 24h
    day_ago = datetime.utcnow() - timedelta(hours=24)
    earliest_today = (
        session.query(FundState)
        .filter(
            FundState.trading_mode == trading_mode,
            FundState.created_at >= day_ago,
        )
        .order_by(FundState.created_at.asc())
        .first()
    )
    start_of_day_equity = (
        earliest_today.equity if earliest_today else equity
    )
    daily_pnl = round(equity - start_of_day_equity, 2)

    return {
        "cash": cash,
        "equity": equity,
        "total_market_value": round(total_market_value, 2),
        "total_cost_basis": round(total_cost_basis, 2),
        "total_realized_pnl": round(total_realized, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "peak_equity": round(peak_equity, 2),
        "drawdown_pct": drawdown_pct,
        "daily_pnl": daily_pnl,
        "position_count": len(positions),
    }


def persist_fund_state(
    trading_mode: str,
    halted: bool = False,
    halt_reason: str | None = None,
) -> dict[str, Any]:
    """Recompute fund state from current positions and persist a new row."""
    with get_db() as session:
        snapshot = compute_fund_state(session, trading_mode)
        state = FundState(
            trading_mode=trading_mode,
            cash=snapshot["cash"],
            equity=snapshot["equity"],
            total_realized_pnl=snapshot["total_realized_pnl"],
            total_unrealized_pnl=snapshot["total_unrealized_pnl"],
            peak_equity=snapshot["peak_equity"],
            drawdown_pct=snapshot["drawdown_pct"],
            daily_pnl=snapshot["daily_pnl"],
            trading_halted=halted,
            halt_reason=halt_reason,
        )
        session.add(state)
        session.flush()
        logger.info(
            "fund_state_persisted",
            equity=snapshot["equity"],
            drawdown_pct=snapshot["drawdown_pct"],
            daily_pnl=snapshot["daily_pnl"],
            halted=halted,
        )
        return snapshot


def check_pre_trade(
    ticker: str,
    side: str,
    notional: float,
) -> GuardDecision:
    """
    Pre-trade risk check. Returns a GuardDecision.

    Guards:
        1. Trading halted (manual flag or previous breach)
        2. Max drawdown
        3. Max daily loss
        4. Max position size (% of equity)
    """
    settings = get_settings()
    trading_mode = settings.trading_mode

    with get_db() as session:
        snapshot = compute_fund_state(session, trading_mode)
        latest = (
            session.query(FundState)
            .filter_by(trading_mode=trading_mode)
            .order_by(FundState.created_at.desc())
            .first()
        )

        # Guard 1: trading halted flag
        if latest and latest.trading_halted:
            decision = GuardDecision(
                allowed=False,
                reason=latest.halt_reason or "trading halted",
                guard="trading_halted",
            )
            logger.warning(
                "risk_guard_block",
                guard="trading_halted",
                reason=decision.reason,
            )
            return decision

        equity = snapshot["equity"]
        if equity <= 0:
            return GuardDecision(
                allowed=False,
                reason=f"equity <= 0 ({equity})",
                guard="equity",
            )

        # Guard 2: max drawdown
        if snapshot["drawdown_pct"] > settings.max_drawdown_pct:
            decision = GuardDecision(
                allowed=False,
                reason=(
                    f"drawdown {snapshot['drawdown_pct']}% > "
                    f"max {settings.max_drawdown_pct}%"
                ),
                guard="max_drawdown",
            )
            logger.warning(
                "risk_guard_block",
                guard="max_drawdown",
                drawdown=snapshot["drawdown_pct"],
            )
            return decision

        # Guard 3: daily loss
        daily_loss_pct = (
            abs(snapshot["daily_pnl"]) / snapshot["peak_equity"] * 100
            if snapshot["daily_pnl"] < 0 and snapshot["peak_equity"] > 0
            else 0.0
        )
        if daily_loss_pct > settings.max_daily_loss_pct:
            decision = GuardDecision(
                allowed=False,
                reason=(
                    f"daily loss {round(daily_loss_pct, 2)}% > "
                    f"max {settings.max_daily_loss_pct}%"
                ),
                guard="daily_loss",
            )
            logger.warning(
                "risk_guard_block",
                guard="daily_loss",
                daily_pnl=snapshot["daily_pnl"],
            )
            return decision

        # Guard 4: max position size (for buys only)
        if side == "buy":
            position = (
                session.query(Position)
                .filter_by(ticker=ticker.upper(), trading_mode=trading_mode)
                .first()
            )
            existing_value = position.market_value or 0.0 if position else 0.0
            new_value = existing_value + notional
            position_pct = new_value / equity * 100 if equity > 0 else 100.0
            if position_pct > settings.max_position_pct:
                decision = GuardDecision(
                    allowed=False,
                    reason=(
                        f"position {ticker} would be {round(position_pct, 2)}% "
                        f"> max {settings.max_position_pct}%"
                    ),
                    guard="max_position",
                )
                logger.warning(
                    "risk_guard_block",
                    guard="max_position",
                    ticker=ticker,
                    position_pct=round(position_pct, 2),
                )
                return decision

    logger.info(
        "risk_guard_allowed",
        ticker=ticker,
        side=side,
        notional=notional,
    )
    return GuardDecision(allowed=True)


def halt_trading(reason: str, trading_mode: str | None = None) -> None:
    """Manually halt trading."""
    mode = trading_mode or get_settings().trading_mode
    persist_fund_state(mode, halted=True, halt_reason=reason)
    logger.error("trading_halted", reason=reason, mode=mode)


def resume_trading(trading_mode: str | None = None) -> None:
    """Resume trading (clear halt flag)."""
    mode = trading_mode or get_settings().trading_mode
    persist_fund_state(mode, halted=False, halt_reason=None)
    logger.info("trading_resumed", mode=mode)
