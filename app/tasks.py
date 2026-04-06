import asyncio
import uuid
from typing import Literal
from app.celery_app import celery_app
from app.context import AnalysisContext
from app.coordinator import run_analysis
from app.db import get_db
from app.models import AnalysisResult
from app.version import MODEL_VERSION, DATA_VERSION
from app.logging import get_logger

logger = get_logger(__name__)


def _run_async(coro):
    """Run async function in sync context for Celery."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(bind=True, name="app.tasks.analyze_ticker")
def analyze_ticker(
    self,
    ticker: str,
    user_id: str | None = None,
    asset_type: str = "equity",
):
    request_id = self.request.id or str(uuid.uuid4())
    logger.info(
        "task_started",
        ticker=ticker,
        request_id=request_id,
        asset_type=asset_type,
    )

    # Create pending record
    try:
        with get_db() as session:
            record = AnalysisResult(
                request_id=request_id,
                ticker=ticker.upper(),
                status="processing",
                model_version=MODEL_VERSION,
                data_version=DATA_VERSION,
            )
            session.add(record)
    except Exception as e:
        logger.error("task_db_init_error", error=str(e))

    ctx = AnalysisContext(
        ticker=ticker,
        request_id=request_id,
        asset_type=asset_type,
        user_id=user_id,
    )

    try:
        result = _run_async(run_analysis(ctx))
        return result
    except Exception as e:
        logger.error("task_failed", ticker=ticker, error=str(e))
        try:
            with get_db() as session:
                record = (
                    session.query(AnalysisResult)
                    .filter_by(request_id=request_id)
                    .first()
                )
                if record:
                    record.status = "failed"
                    record.error = str(e)
        except Exception:
            pass
        raise


@celery_app.task(name="app.tasks.analyze_batch")
def analyze_batch(
    tickers: list[str],
    user_id: str | None = None,
    asset_type: str = "equity",
):
    logger.info("batch_started", tickers=tickers, asset_type=asset_type)
    task_ids = []
    for ticker in tickers:
        task = analyze_ticker.delay(ticker, user_id, asset_type)
        task_ids.append({"ticker": ticker, "task_id": task.id})
    return task_ids
