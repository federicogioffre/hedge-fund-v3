from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from app.config import get_settings
from app.models import Base


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def init_db():
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db() -> Session:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_recent_signal_history(
    session: Session,
    ticker: str,
    agent_name: str,
    limit: int = 5,
) -> list[dict]:
    """
    Load recent signal history for a ticker+agent pair.
    Ordered by created_at DESC, returns list of dicts.
    """
    from app.models import SignalHistory

    records = (
        session.query(SignalHistory)
        .filter_by(ticker=ticker.upper(), agent_name=agent_name)
        .order_by(SignalHistory.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "agent_name": r.agent_name,
            "score": r.score,
            "confidence": r.confidence,
            "risk": r.risk,
            "momentum": r.momentum,
            "acceleration": r.acceleration,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
