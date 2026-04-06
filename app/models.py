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
