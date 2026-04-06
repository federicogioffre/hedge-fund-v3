from datetime import datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.tasks import analyze_ticker, analyze_batch
from app.db import get_db
from app.models import AnalysisResult, RankingSnapshot, PnLTrack
from app.cache import get_cached_analysis, invalidate_cache
from app.risk_engine import compute_risk
from app.signal_blender import blend_signals
from app.portfolio_engine import construct_portfolio
from app.backtest import run_backtest_v2
from app.data_bundle import DataBundle
from app.agents import AGENTS
from app.version import MODEL_VERSION, DATA_VERSION, APP_VERSION
from app.logging import get_logger
from celery.result import AsyncResult
import asyncio

logger = get_logger(__name__)

router = APIRouter()


# --- Request/Response schemas ---


class AnalyzeRequest(BaseModel):
    ticker: str
    asset_type: Literal["equity", "crypto"] = "equity"
    user_id: str | None = None


class BatchAnalyzeRequest(BaseModel):
    tickers: list[str]
    asset_type: Literal["equity", "crypto"] = "equity"
    user_id: str | None = None


class AnalysisResponse(BaseModel):
    request_id: str
    ticker: str
    status: str
    message: str


# --- Existing Endpoints (backward-compatible) ---


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

    task = analyze_ticker.delay(ticker, req.user_id, req.asset_type)
    logger.info(
        "analysis_queued",
        ticker=ticker,
        task_id=task.id,
        asset_type=req.asset_type,
    )

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
    task = analyze_batch.delay(tickers, req.user_id, req.asset_type)

    return {
        "batch_id": task.id,
        "tickers": tickers,
        "asset_type": req.asset_type,
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
    limit: int = Query(default=25, ge=1, le=100),
):
    with get_db() as session:
        from sqlalchemy import func, desc

        # Get latest analysis per ticker (max 25)
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
            # Parse agent_results to extract blended/risk if stored
            agent_data = r.agent_results or []
            blended_score = None
            risk_score = None

            # Try to reconstruct blended and risk from agent_results
            if agent_data:
                scores = [a.get("score", 3.0) for a in agent_data]
                confidences = [a.get("confidence", 0.5) for a in agent_data]
                risks = [a.get("risk", 0.3) for a in agent_data]

                if scores:
                    blended_score = round(sum(scores) / len(scores), 2)
                if risks:
                    risk_score = round(sum(risks) / len(risks), 3)

            # Conviction = score * confidence * (1 - risk)
            conviction = r.conviction
            if conviction is None and r.overall_score and r.confidence:
                avg_risk = risk_score or 0.3
                conviction = round(
                    r.overall_score * r.confidence * (1 - avg_risk), 2
                )

            ranking.append(
                {
                    "rank": rank,
                    "ticker": r.ticker,
                    "overall_score": r.overall_score,
                    "blended_score": blended_score,
                    "confidence": r.confidence,
                    "conviction": conviction,
                    "risk_score": risk_score,
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


# --- V5 NEW ENDPOINTS ---


def _run_async(coro):
    """Helper to run async code from sync FastAPI endpoints."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@router.get("/portfolio")
def get_portfolio(
    tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT"),
    capital: float = Query(default=100_000.0, ge=1000),
    asset_type: Literal["equity", "crypto"] = "equity",
):
    """Construct portfolio from given tickers using latest analysis data."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list or len(ticker_list) > 25:
        raise HTTPException(status_code=400, detail="Provide 1-25 tickers")

    # Gather latest analysis for each ticker from DB
    rankings = []
    with get_db() as session:
        for ticker in ticker_list:
            record = (
                session.query(AnalysisResult)
                .filter_by(ticker=ticker, status="completed")
                .order_by(AnalysisResult.created_at.desc())
                .first()
            )
            if record:
                agent_data = record.agent_results or []
                risks = [a.get("risk", 0.3) for a in agent_data]
                risk_score = round(sum(risks) / len(risks), 3) if risks else 0.3

                rankings.append({
                    "ticker": record.ticker,
                    "overall_score": record.overall_score or 3.0,
                    "confidence": record.confidence or 0.5,
                    "conviction": record.conviction or 0.0,
                    "risk_score": risk_score,
                    "recommendation": record.recommendation or "hold",
                })

    if not rankings:
        raise HTTPException(
            status_code=404,
            detail="No completed analysis found for the given tickers. Run /analyze first.",
        )

    portfolio = construct_portfolio(rankings, capital)
    portfolio["model_version"] = MODEL_VERSION
    portfolio["timestamp"] = datetime.utcnow().isoformat()
    return portfolio


@router.get("/backtest-v2")
def backtest_v2(
    tickers: str = Query(..., description="Comma-separated tickers"),
    days: int = Query(default=30, ge=1, le=365),
    capital: float = Query(default=100_000.0, ge=1000),
):
    """Run backtest V2 simulation."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list or len(ticker_list) > 25:
        raise HTTPException(status_code=400, detail="Provide 1-25 tickers")

    result = run_backtest_v2(ticker_list, days=days, capital=capital)
    result["model_version"] = MODEL_VERSION
    result["timestamp"] = datetime.utcnow().isoformat()
    return result


@router.get("/risk/{ticker}")
def get_risk(
    ticker: str,
    asset_type: Literal["equity", "crypto"] = "equity",
):
    """Compute risk metrics for a single ticker."""
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    async def _compute():
        bundle = DataBundle(ticker=ticker, asset_type=asset_type)
        await bundle.load()

        agent_tasks = [agent.safe_analyze(bundle) for agent in AGENTS]
        agent_results = await asyncio.gather(*agent_tasks, return_exceptions=True)
        valid_results = [r for r in agent_results if not isinstance(r, Exception)]

        risk_metrics = compute_risk(bundle, valid_results)
        blended = blend_signals(valid_results)

        return {
            "ticker": ticker,
            "asset_type": asset_type,
            "risk_metrics": risk_metrics,
            "blended_signal": blended,
            "model_version": MODEL_VERSION,
            "timestamp": datetime.utcnow().isoformat(),
        }

    return _run_async(_compute())


@router.get("/pnl")
def get_pnl(
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get PnL tracking records."""
    with get_db() as session:
        records = (
            session.query(PnLTrack)
            .order_by(PnLTrack.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "positions": [
                {
                    "id": r.id,
                    "ticker": r.ticker,
                    "asset_type": r.asset_type,
                    "position_size": r.position_size,
                    "entry_price": r.entry_price,
                    "current_price": r.current_price,
                    "pnl": r.pnl,
                    "pnl_pct": r.pnl_pct,
                    "created_at": r.created_at.isoformat()
                    if r.created_at
                    else None,
                }
                for r in records
            ],
            "count": len(records),
            "timestamp": datetime.utcnow().isoformat(),
        }


@router.post("/pnl/simulate")
def simulate_pnl(
    tickers: str = Query(..., description="Comma-separated tickers"),
    capital: float = Query(default=100_000.0, ge=1000),
):
    """Run PnL simulation and store results."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list or len(ticker_list) > 25:
        raise HTTPException(status_code=400, detail="Provide 1-25 tickers")

    return _update_pnl_simulation(ticker_list, capital)


def _update_pnl_simulation(
    tickers: list[str], capital: float = 100_000.0
) -> dict:
    """Generate and store simulated PnL entries."""
    import hashlib
    import random

    positions = []

    # Build rankings from DB
    rankings = []
    with get_db() as session:
        for ticker in tickers:
            record = (
                session.query(AnalysisResult)
                .filter_by(ticker=ticker, status="completed")
                .order_by(AnalysisResult.created_at.desc())
                .first()
            )
            if record:
                rankings.append({
                    "ticker": record.ticker,
                    "overall_score": record.overall_score or 3.0,
                    "confidence": record.confidence or 0.5,
                    "conviction": record.conviction or 0.0,
                    "risk_score": 0.3,
                    "recommendation": record.recommendation or "hold",
                })

    if not rankings:
        # Simulated entries if no analysis exists
        for ticker in tickers:
            seed = int(hashlib.md5(ticker.encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)
            entry_price = 50 + rng.random() * 450
            current_price = entry_price * (1 + rng.gauss(0.01, 0.05))
            size = capital / len(tickers)
            pnl = size * (current_price - entry_price) / entry_price
            pnl_pct = ((current_price - entry_price) / entry_price) * 100

            rankings.append({
                "ticker": ticker,
                "overall_score": 3.0,
                "confidence": 0.5,
                "conviction": 0.0,
                "risk_score": 0.3,
                "recommendation": "hold",
            })

    portfolio = construct_portfolio(rankings, capital)

    try:
        with get_db() as session:
            for pos in portfolio["positions"]:
                ticker = pos["ticker"]
                seed = int(hashlib.md5(ticker.encode()).hexdigest()[:8], 16)
                rng = random.Random(seed)
                entry_price = round(50 + rng.random() * 450, 2)
                daily_return = rng.gauss(0.002, 0.03)
                current_price = round(entry_price * (1 + daily_return), 2)
                pnl = round(
                    pos["allocation"] * (current_price - entry_price) / entry_price, 2
                )
                pnl_pct = round(
                    ((current_price - entry_price) / entry_price) * 100, 3
                )

                record = PnLTrack(
                    ticker=ticker,
                    asset_type="equity",
                    position_size=pos["allocation"],
                    entry_price=entry_price,
                    current_price=current_price,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                )
                session.add(record)
                positions.append({
                    "ticker": ticker,
                    "position_size": pos["allocation"],
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                })
    except Exception as e:
        logger.error("pnl_simulation_error", error=str(e))
        raise HTTPException(status_code=500, detail="PnL simulation failed")

    total_pnl = sum(p["pnl"] for p in positions)
    return {
        "positions": positions,
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / capital * 100, 3) if capital > 0 else 0,
        "capital": capital,
        "timestamp": datetime.utcnow().isoformat(),
    }
