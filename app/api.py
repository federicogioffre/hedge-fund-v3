import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.tasks import analyze_ticker, analyze_batch
from app.db import get_db
from app.models import AnalysisResult, RankingSnapshot
from app.cache import get_cached_analysis, invalidate_cache
from app.version import MODEL_VERSION, DATA_VERSION, APP_VERSION
from app.logging import get_logger
from celery.result import AsyncResult

logger = get_logger(__name__)

router = APIRouter()


# --- Request/Response schemas ---


class AnalyzeRequest(BaseModel):
    ticker: str
    user_id: str | None = None


class BatchAnalyzeRequest(BaseModel):
    tickers: list[str]
    user_id: str | None = None


class AnalysisResponse(BaseModel):
    request_id: str
    ticker: str
    status: str
    message: str


# --- Endpoints ---


@router.get("/health")
def health():
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "model_version": MODEL_VERSION,
        "data_version": DATA_VERSION,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(req: AnalyzeRequest):
    ticker = req.ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    task = analyze_ticker.delay(ticker, req.user_id)
    logger.info("analysis_queued", ticker=ticker, task_id=task.id)

    return AnalysisResponse(
        request_id=task.id,
        ticker=ticker,
        status="queued",
        message=f"Analysis queued for {ticker}",
    )


@router.post("/analyze/batch")
def batch_analyze(req: BatchAnalyzeRequest):
    if not req.tickers or len(req.tickers) > 20:
        raise HTTPException(
            status_code=400, detail="Provide 1-20 tickers"
        )

    tickers = [t.upper().strip() for t in req.tickers]
    task = analyze_batch.delay(tickers, req.user_id)

    return {
        "batch_id": task.id,
        "tickers": tickers,
        "status": "queued",
        "message": f"Batch analysis queued for {len(tickers)} tickers",
    }


@router.get("/analysis/{request_id}")
def get_analysis(request_id: str):
    # Check Celery task status
    task_result = AsyncResult(request_id)

    if task_result.state == "PENDING":
        return {"request_id": request_id, "status": "pending"}
    elif task_result.state == "STARTED":
        return {"request_id": request_id, "status": "processing"}
    elif task_result.state == "SUCCESS":
        return task_result.result
    elif task_result.state == "FAILURE":
        return {
            "request_id": request_id,
            "status": "failed",
            "error": str(task_result.info),
        }

    # Fallback: check DB
    with get_db() as session:
        record = (
            session.query(AnalysisResult)
            .filter_by(request_id=request_id)
            .first()
        )
        if record:
            return {
                "request_id": record.request_id,
                "ticker": record.ticker,
                "status": record.status,
                "overall_score": record.overall_score,
                "confidence": record.confidence,
                "conviction": record.conviction,
                "recommendation": record.recommendation,
                "report": record.report,
                "model_version": record.model_version,
                "created_at": record.created_at.isoformat()
                if record.created_at
                else None,
            }

    raise HTTPException(status_code=404, detail="Analysis not found")


@router.get("/analysis/ticker/{ticker}")
def get_analysis_by_ticker(
    ticker: str,
    limit: int = Query(default=10, ge=1, le=100),
):
    ticker = ticker.upper().strip()

    # Check cache for latest
    cached = get_cached_analysis(ticker)
    if cached:
        return {"source": "cache", "result": cached}

    with get_db() as session:
        records = (
            session.query(AnalysisResult)
            .filter_by(ticker=ticker, status="completed")
            .order_by(AnalysisResult.created_at.desc())
            .limit(limit)
            .all()
        )

        if not records:
            raise HTTPException(
                status_code=404, detail=f"No analysis found for {ticker}"
            )

        return {
            "source": "database",
            "ticker": ticker,
            "count": len(records),
            "results": [
                {
                    "request_id": r.request_id,
                    "overall_score": r.overall_score,
                    "confidence": r.confidence,
                    "conviction": r.conviction,
                    "recommendation": r.recommendation,
                    "model_version": r.model_version,
                    "created_at": r.created_at.isoformat()
                    if r.created_at
                    else None,
                }
                for r in records
            ],
        }


@router.get("/ranking")
def get_ranking(
    limit: int = Query(default=20, ge=1, le=100),
):
    with get_db() as session:
        from sqlalchemy import func, desc

        # Get latest analysis per ticker
        subquery = (
            session.query(
                AnalysisResult.ticker,
                func.max(AnalysisResult.id).label("max_id"),
            )
            .filter(AnalysisResult.status == "completed")
            .group_by(AnalysisResult.ticker)
            .subquery()
        )

        records = (
            session.query(AnalysisResult)
            .join(subquery, AnalysisResult.id == subquery.c.max_id)
            .order_by(desc(AnalysisResult.conviction))
            .limit(limit)
            .all()
        )

        ranking = []
        for rank, r in enumerate(records, 1):
            ranking.append(
                {
                    "rank": rank,
                    "ticker": r.ticker,
                    "overall_score": r.overall_score,
                    "confidence": r.confidence,
                    "conviction": r.conviction,
                    "recommendation": r.recommendation,
                    "model_version": r.model_version,
                    "analyzed_at": r.created_at.isoformat()
                    if r.created_at
                    else None,
                }
            )

        return {
            "ranking": ranking,
            "count": len(ranking),
            "model_version": MODEL_VERSION,
            "timestamp": datetime.utcnow().isoformat(),
        }


@router.delete("/cache/{ticker}")
def clear_cache(ticker: str):
    ticker = ticker.upper().strip()
    invalidate_cache(ticker)
    return {"message": f"Cache cleared for {ticker}"}
