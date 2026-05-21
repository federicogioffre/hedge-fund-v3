import asyncio
import uuid

from app.celery_app import celery_app
from app.config import get_settings
from app.context import AnalysisContext
from app.coordinator import run_analysis
from app.db import get_db
from app.email_service import send_email
from app.logging import get_logger
from app.models import AnalysisResult, FundState, Position
from app.report_builder import build_report_html
from sqlalchemy import desc, func

logger = get_logger(__name__)


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(
    bind=True,
    name="app.tasks_reporting.send_daily_report",
    soft_time_limit=900,
    time_limit=960,
)
def send_daily_report(self):
    settings = get_settings()
    watchlist = [t.strip().upper() for t in settings.report_watchlist.split(",") if t.strip()]
    recipients = [r.strip() for r in settings.report_recipients.split(",") if r.strip()]

    if not watchlist:
        logger.warning("report_skipped", reason="empty_watchlist")
        return {"status": "skipped", "reason": "empty_watchlist"}

    logger.info("report_started", tickers=len(watchlist))

    completed = []
    failed = []
    for ticker in watchlist:
        try:
            ctx = AnalysisContext(
                ticker=ticker,
                request_id=str(uuid.uuid4()),
                asset_type="equity",
            )
            _run_async(run_analysis(ctx))
            completed.append(ticker)
            logger.info("report_ticker_done", ticker=ticker)
        except Exception as e:
            logger.warning("report_ticker_failed", ticker=ticker, error=str(e))
            failed.append(ticker)

    rankings = _get_latest_rankings(watchlist)
    fund_state = _get_fund_state(settings.trading_mode)
    positions = _get_open_positions(settings.trading_mode)

    html = build_report_html(rankings, fund_state, positions)

    from datetime import datetime
    subject = f"Hedge Fund V7 — Daily Report — {datetime.utcnow().strftime('%Y-%m-%d')}"

    email_sent = send_email(subject, html, recipients)

    result = {
        "status": "sent" if email_sent else "generated",
        "tickers_analyzed": len(completed),
        "tickers_failed": len(failed),
        "rankings": len(rankings),
        "email_sent": email_sent,
    }
    if failed:
        result["failed_tickers"] = failed

    logger.info("report_completed", **result)
    return result


def _get_latest_rankings(tickers: list[str]) -> list[dict]:
    with get_db() as session:
        subquery = (
            session.query(
                AnalysisResult.ticker,
                func.max(AnalysisResult.id).label("max_id"),
            )
            .filter(
                AnalysisResult.ticker.in_(tickers),
                AnalysisResult.status == "completed",
            )
            .group_by(AnalysisResult.ticker)
            .subquery()
        )

        records = (
            session.query(AnalysisResult)
            .join(subquery, AnalysisResult.id == subquery.c.max_id)
            .order_by(desc(AnalysisResult.conviction))
            .all()
        )

        return [
            {
                "ticker": r.ticker,
                "overall_score": r.overall_score,
                "confidence": r.confidence,
                "conviction": r.conviction,
                "recommendation": r.recommendation,
            }
            for r in records
        ]


def _get_fund_state(trading_mode: str) -> dict | None:
    with get_db() as session:
        latest = (
            session.query(FundState)
            .filter_by(trading_mode=trading_mode)
            .order_by(FundState.created_at.desc())
            .first()
        )
        if not latest:
            return None
        return {
            "equity": latest.equity,
            "cash": latest.cash,
            "daily_pnl": latest.daily_pnl,
            "drawdown_pct": latest.drawdown_pct,
            "trading_halted": latest.trading_halted,
        }


def _get_open_positions(trading_mode: str) -> list[dict]:
    with get_db() as session:
        records = (
            session.query(Position)
            .filter(
                Position.trading_mode == trading_mode,
                Position.quantity > 0,
            )
            .order_by(desc(Position.market_value))
            .all()
        )
        return [
            {
                "ticker": p.ticker,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
            }
            for p in records
        ]
