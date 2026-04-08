"""
V6 Execution Engine.

Simulated broker interface supporting market orders with a basic slippage
model. All executions are persisted to the database. Paper/live mode is
controlled by Settings.trading_mode.

Async-safe: uses an asyncio.Lock per ticker to serialize position updates,
and wraps DB writes in transactions for atomicity. Idempotent: submitting an
order with an existing client_order_id returns the original record without
re-executing.
"""

import asyncio
import hashlib
import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.data_sources import fetch_market_data
from app.db import get_db
from app.logging import get_logger
from app.models import Order, Position

logger = get_logger(__name__)

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market"]


# Per-ticker locks to serialize position mutations within a single process.
_ticker_locks: dict[str, asyncio.Lock] = {}


def _lock_for(ticker: str) -> asyncio.Lock:
    ticker = ticker.upper()
    if ticker not in _ticker_locks:
        _ticker_locks[ticker] = asyncio.Lock()
    return _ticker_locks[ticker]


def _make_client_order_id(
    ticker: str, side: str, size: float, nonce: str | None = None
) -> str:
    """Deterministic id when nonce is provided → idempotency on retries."""
    payload = f"{ticker}:{side}:{size}:{nonce or uuid.uuid4().hex}"
    return hashlib.sha1(payload.encode()).hexdigest()[:32]


def _apply_slippage(reference_price: float, side: OrderSide, bps: float) -> float:
    """Buys pay up, sells get hit. bps = basis points (1bp = 0.01%)."""
    adj = reference_price * (bps / 10_000.0)
    return reference_price + adj if side == "buy" else reference_price - adj


class ExecutionEngine:
    """Simulated broker with persistence."""

    def __init__(self, trading_mode: str | None = None):
        settings = get_settings()
        self.trading_mode: str = trading_mode or settings.trading_mode
        self.slippage_bps: float = settings.slippage_bps

    # ----- PUBLIC API -----

    async def place_order(
        self,
        ticker: str,
        side: OrderSide,
        size: float,
        order_type: OrderType = "market",
        client_order_id: str | None = None,
        reference_price: float | None = None,
    ) -> dict[str, Any]:
        """
        Submit a market order. Returns the persisted order as a dict.

        Idempotent: if client_order_id already exists, returns the existing
        record unchanged.
        """
        ticker = ticker.upper().strip()
        if size <= 0:
            raise ValueError(f"size must be > 0, got {size}")
        if side not in ("buy", "sell"):
            raise ValueError(f"invalid side: {side}")

        client_order_id = client_order_id or _make_client_order_id(
            ticker, side, size
        )

        # Idempotency check
        existing = self._find_order(client_order_id)
        if existing is not None:
            logger.info(
                "order_idempotent_hit",
                client_order_id=client_order_id,
                ticker=ticker,
            )
            return existing

        # Resolve reference price
        if reference_price is None:
            market = await fetch_market_data(ticker, "equity")
            reference_price = float(market.get("price", 0.0))
        if reference_price <= 0:
            return self._reject_order(
                client_order_id=client_order_id,
                ticker=ticker,
                side=side,
                size=size,
                order_type=order_type,
                reason=f"invalid reference price: {reference_price}",
            )

        fill_price = _apply_slippage(reference_price, side, self.slippage_bps)
        notional = round(fill_price * size, 2)

        logger.info(
            "order_placing",
            client_order_id=client_order_id,
            ticker=ticker,
            side=side,
            size=size,
            reference_price=reference_price,
            fill_price=fill_price,
            trading_mode=self.trading_mode,
        )

        async with _lock_for(ticker):
            # DB write + position update in a single transaction
            order_dict = await asyncio.to_thread(
                self._persist_fill,
                client_order_id,
                ticker,
                side,
                size,
                order_type,
                reference_price,
                fill_price,
                notional,
            )

        logger.info(
            "order_filled",
            client_order_id=client_order_id,
            ticker=ticker,
            fill_price=fill_price,
            notional=notional,
        )
        return order_dict

    async def cancel_order(self, client_order_id: str) -> dict[str, Any]:
        """
        Cancel a pending order. Filled orders cannot be cancelled.
        For the simulated broker, market orders fill immediately, so this
        mostly serves as an API contract.
        """
        with get_db() as session:
            order = (
                session.query(Order)
                .filter_by(client_order_id=client_order_id)
                .first()
            )
            if order is None:
                raise ValueError(f"order not found: {client_order_id}")
            if order.status == "filled":
                raise ValueError(
                    f"cannot cancel filled order {client_order_id}"
                )
            if order.status == "cancelled":
                return _order_to_dict(order)

            order.status = "cancelled"
            order.reason = "cancelled by user"
            session.flush()
            result = _order_to_dict(order)

        logger.info("order_cancelled", client_order_id=client_order_id)
        return result

    def get_positions(self) -> list[dict[str, Any]]:
        """Return all non-closed positions in the current trading mode."""
        with get_db() as session:
            records = (
                session.query(Position)
                .filter(
                    Position.trading_mode == self.trading_mode,
                    Position.quantity != 0,
                )
                .order_by(Position.ticker)
                .all()
            )
            return [_position_to_dict(p) for p in records]

    async def mark_to_market(self) -> list[dict[str, Any]]:
        """Refresh current_price and unrealized_pnl for all open positions."""
        positions = self.get_positions()
        updated: list[dict[str, Any]] = []
        for pos in positions:
            try:
                market = await fetch_market_data(pos["ticker"], "equity")
                price = float(market.get("price", 0.0))
            except Exception as e:
                logger.warning(
                    "mtm_fetch_error", ticker=pos["ticker"], error=str(e)
                )
                continue

            with get_db() as session:
                p = (
                    session.query(Position)
                    .filter_by(
                        ticker=pos["ticker"],
                        trading_mode=self.trading_mode,
                    )
                    .first()
                )
                if p is None or p.quantity == 0:
                    continue
                p.current_price = price
                p.market_value = round(price * p.quantity, 2)
                p.unrealized_pnl = round(
                    (price - p.avg_entry_price) * p.quantity, 2
                )
                session.flush()
                updated.append(_position_to_dict(p))

        logger.info("positions_marked_to_market", count=len(updated))
        return updated

    # ----- INTERNALS -----

    def _find_order(self, client_order_id: str) -> dict[str, Any] | None:
        with get_db() as session:
            order = (
                session.query(Order)
                .filter_by(client_order_id=client_order_id)
                .first()
            )
            return _order_to_dict(order) if order else None

    def _reject_order(
        self,
        client_order_id: str,
        ticker: str,
        side: str,
        size: float,
        order_type: str,
        reason: str,
    ) -> dict[str, Any]:
        with get_db() as session:
            order = Order(
                client_order_id=client_order_id,
                ticker=ticker,
                side=side,
                order_type=order_type,
                requested_qty=size,
                filled_qty=0.0,
                status="rejected",
                trading_mode=self.trading_mode,
                reason=reason,
            )
            session.add(order)
            session.flush()
            result = _order_to_dict(order)
        logger.warning(
            "order_rejected",
            client_order_id=client_order_id,
            ticker=ticker,
            reason=reason,
        )
        return result

    def _persist_fill(
        self,
        client_order_id: str,
        ticker: str,
        side: str,
        size: float,
        order_type: str,
        reference_price: float,
        fill_price: float,
        notional: float,
    ) -> dict[str, Any]:
        """Atomic: insert Order + update Position in a single transaction."""
        with get_db() as session:
            order = Order(
                client_order_id=client_order_id,
                broker_order_id=f"SIM-{uuid.uuid4().hex[:12]}",
                ticker=ticker,
                side=side,
                order_type=order_type,
                requested_qty=size,
                filled_qty=size,
                requested_price=reference_price,
                fill_price=fill_price,
                slippage_bps=self.slippage_bps,
                notional=notional,
                status="filled",
                trading_mode=self.trading_mode,
                filled_at=datetime.utcnow(),
            )
            session.add(order)

            self._update_position(
                session, ticker, side, size, fill_price
            )

            session.flush()
            return _order_to_dict(order)

    def _update_position(
        self,
        session: Session,
        ticker: str,
        side: str,
        size: float,
        fill_price: float,
    ) -> None:
        position = (
            session.query(Position)
            .filter_by(ticker=ticker, trading_mode=self.trading_mode)
            .first()
        )

        if position is None:
            position = Position(
                ticker=ticker,
                trading_mode=self.trading_mode,
                quantity=0.0,
                avg_entry_price=0.0,
                cost_basis=0.0,
            )
            session.add(position)
            session.flush()

        old_qty = position.quantity
        old_avg = position.avg_entry_price
        old_cost_basis = position.cost_basis

        if side == "buy":
            new_qty = old_qty + size
            if new_qty == 0:
                new_avg = 0.0
            else:
                new_cost_basis = old_cost_basis + size * fill_price
                new_avg = new_cost_basis / new_qty
            position.quantity = round(new_qty, 6)
            position.avg_entry_price = round(new_avg, 4)
            position.cost_basis = round(
                old_cost_basis + size * fill_price, 2
            )
        else:  # sell
            # Realize PnL on the sold portion at avg_entry_price
            sell_qty = min(size, old_qty) if old_qty > 0 else size
            realized_delta = (fill_price - old_avg) * sell_qty
            position.realized_pnl = round(
                (position.realized_pnl or 0.0) + realized_delta, 2
            )
            new_qty = old_qty - size
            if new_qty <= 0.0000001 and new_qty >= -0.0000001:
                new_qty = 0.0
                position.avg_entry_price = 0.0
                position.cost_basis = 0.0
            else:
                # Reduce cost basis proportionally
                if old_qty > 0:
                    position.cost_basis = round(
                        old_cost_basis * (new_qty / old_qty), 2
                    )
                # avg_entry_price unchanged on reduction
            position.quantity = round(new_qty, 6)

        position.current_price = fill_price
        position.market_value = round(
            position.quantity * fill_price, 2
        )
        position.unrealized_pnl = round(
            (fill_price - position.avg_entry_price) * position.quantity, 2
        ) if position.quantity != 0 else 0.0
        position.last_updated = datetime.utcnow()


def _order_to_dict(order: Order | None) -> dict[str, Any] | None:
    if order is None:
        return None
    return {
        "id": order.id,
        "client_order_id": order.client_order_id,
        "broker_order_id": order.broker_order_id,
        "ticker": order.ticker,
        "side": order.side,
        "order_type": order.order_type,
        "requested_qty": order.requested_qty,
        "filled_qty": order.filled_qty,
        "requested_price": order.requested_price,
        "fill_price": order.fill_price,
        "slippage_bps": order.slippage_bps,
        "notional": order.notional,
        "status": order.status,
        "trading_mode": order.trading_mode,
        "reason": order.reason,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "filled_at": order.filled_at.isoformat() if order.filled_at else None,
    }


def _position_to_dict(position: Position) -> dict[str, Any]:
    return {
        "id": position.id,
        "ticker": position.ticker,
        "quantity": position.quantity,
        "avg_entry_price": position.avg_entry_price,
        "current_price": position.current_price,
        "market_value": position.market_value,
        "cost_basis": position.cost_basis,
        "realized_pnl": position.realized_pnl,
        "unrealized_pnl": position.unrealized_pnl,
        "trading_mode": position.trading_mode,
        "opened_at": position.opened_at.isoformat()
        if position.opened_at
        else None,
        "last_updated": position.last_updated.isoformat()
        if position.last_updated
        else None,
    }
