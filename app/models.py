from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
    JSON,
    Boolean,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), unique=True, nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    overall_score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    recommendation = Column(String(20), nullable=True)
    conviction = Column(Float, nullable=True)
    agent_results = Column(JSON, nullable=True)
    report = Column(Text, nullable=True)
    model_version = Column(String(20), nullable=False)
    data_version = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_analysis_ticker_created", "ticker", "created_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    agent_name = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(JSON, nullable=True)
    success = Column(Boolean, default=True)
    duration_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RankingSnapshot(Base):
    __tablename__ = "ranking_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    overall_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    conviction = Column(Float, nullable=False)
    recommendation = Column(String(20), nullable=False)
    rank = Column(Integer, nullable=False)
    snapshot_date = Column(DateTime, default=datetime.utcnow, index=True)
    model_version = Column(String(20), nullable=False)


# --- V5 TABLES ---


class PnLTrack(Base):
    __tablename__ = "pnl_tracks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    asset_type = Column(String(10), nullable=False, default="equity")
    position_size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    pnl_pct = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# --- V5.1 TABLES ---


class SignalHistory(Base):
    __tablename__ = "signal_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    agent_name = Column(String(50), nullable=False, index=True)
    score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    risk = Column(Float, nullable=False)
    momentum = Column(Float, nullable=True)
    acceleration = Column(Float, nullable=True)
    request_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_signal_ticker_agent_created", "ticker", "agent_name", "created_at"),
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    horizon = Column(String(20), nullable=False, default="default")
    data_json = Column(JSON, nullable=False)
    model_version = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# --- V6 TRADING ENGINE TABLES (additive only) ---


class Order(Base):
    """
    Persistent record of every order submitted to the execution engine.
    Idempotent: client_order_id is unique.
    """

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_order_id = Column(String(64), unique=True, nullable=False, index=True)
    broker_order_id = Column(String(64), nullable=True)
    ticker = Column(String(10), nullable=False, index=True)
    side = Column(String(4), nullable=False)  # "buy" or "sell"
    order_type = Column(String(20), nullable=False, default="market")
    requested_qty = Column(Float, nullable=False)
    filled_qty = Column(Float, nullable=False, default=0.0)
    requested_price = Column(Float, nullable=True)  # None for market
    fill_price = Column(Float, nullable=True)
    slippage_bps = Column(Float, nullable=True)
    notional = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    # statuses: pending, filled, cancelled, rejected
    trading_mode = Column(String(10), nullable=False, default="paper")
    reason = Column(Text, nullable=True)  # rejection reason or notes
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    filled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_orders_ticker_status", "ticker", "status"),
    )


class Position(Base):
    """
    Live position state. Single row per ticker (open).
    Closed positions are kept with quantity=0 for audit.
    """

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    quantity = Column(Float, nullable=False, default=0.0)
    avg_entry_price = Column(Float, nullable=False, default=0.0)
    current_price = Column(Float, nullable=True)
    market_value = Column(Float, nullable=True)
    cost_basis = Column(Float, nullable=False, default=0.0)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    trading_mode = Column(String(10), nullable=False, default="paper")
    opened_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("ticker", "trading_mode", name="uq_position_ticker_mode"),
    )


class FundState(Base):
    """
    Snapshot of fund-level state: equity, cash, PnL.
    Append-only; most recent row = current state.
    Used by risk guards to compute drawdown and daily loss.
    """

    __tablename__ = "fund_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trading_mode = Column(String(10), nullable=False, default="paper", index=True)
    cash = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)  # cash + sum(positions market_value)
    total_realized_pnl = Column(Float, nullable=False, default=0.0)
    total_unrealized_pnl = Column(Float, nullable=False, default=0.0)
    peak_equity = Column(Float, nullable=False)
    drawdown_pct = Column(Float, nullable=False, default=0.0)
    daily_pnl = Column(Float, nullable=False, default=0.0)
    trading_halted = Column(Boolean, default=False)
    halt_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
