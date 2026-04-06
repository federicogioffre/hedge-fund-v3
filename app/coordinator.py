import asyncio
import time
from datetime import datetime
from typing import Any
from app.data_bundle import DataBundle
from app.agents import AGENTS, PORTFOLIO_AGENT, AgentResult
from app.cache import get_cached_analysis, set_cached_analysis
from app.context import AnalysisContext
from app.version import MODEL_VERSION, DATA_VERSION
from app.db import get_db
from app.models import AnalysisResult, AuditLog
from app.logging import get_logger

logger = get_logger(__name__)


async def run_analysis(ctx: AnalysisContext) -> dict[str, Any]:
    """
    Full pipeline: DataBundle → Agents → Portfolio → Report
    """
    ticker = ctx.ticker.upper()
    request_id = ctx.request_id

    # Check cache first
    cached = get_cached_analysis(ticker)
    if cached:
        logger.info("using_cached_result", ticker=ticker, request_id=request_id)
        return cached

    start = time.time()
    logger.info("analysis_started", ticker=ticker, request_id=request_id)

    # 1. Load DataBundle (one load, shared across agents)
    bundle = DataBundle(ticker=ticker)
    await bundle.load()

    # 2. Run all agents concurrently
    agent_tasks = [agent.safe_analyze(bundle) for agent in AGENTS]
    agent_results: list[AgentResult] = await asyncio.gather(*agent_tasks)

    # 3. Portfolio agent aggregation
    portfolio = PORTFOLIO_AGENT.analyze_portfolio(agent_results)

    # 4. Build report
    duration_ms = round((time.time() - start) * 1000, 2)
    report = _build_report(ticker, agent_results, portfolio, duration_ms)

    result = {
        "request_id": request_id,
        "ticker": ticker,
        "status": "completed",
        "overall_score": portfolio["overall_score"],
        "confidence": portfolio["confidence"],
        "conviction": portfolio["conviction"],
        "recommendation": portfolio["recommendation"],
        "agent_results": [r.to_dict() for r in agent_results],
        "report": report,
        "model_version": MODEL_VERSION,
        "data_version": DATA_VERSION,
        "duration_ms": duration_ms,
        "completed_at": datetime.utcnow().isoformat(),
    }

    # 5. Save to DB
    _save_result(result)

    # 6. Audit trail
    _save_audit(request_id, ticker, agent_results, duration_ms)

    # 7. Cache result
    set_cached_analysis(ticker, result)

    logger.info(
        "analysis_completed",
        ticker=ticker,
        request_id=request_id,
        score=portfolio["overall_score"],
        recommendation=portfolio["recommendation"],
        duration_ms=duration_ms,
    )

    return result


def _build_report(
    ticker: str,
    agent_results: list[AgentResult],
    portfolio: dict[str, Any],
    duration_ms: float,
) -> str:
    lines = [
        f"=== Hedge Fund V3 Analysis Report ===",
        f"Ticker: {ticker}",
        f"Model: {MODEL_VERSION} | Data: {DATA_VERSION}",
        f"",
        f"--- Agent Scores ---",
    ]
    for r in agent_results:
        fallback = " [FALLBACK]" if r.metadata.get("fallback") else ""
        lines.append(
            f"  {r.agent_name:15s}: score={r.score:.1f}  "
            f"conf={r.confidence:.2f}  risk={r.risk:.2f}{fallback}"
        )
        lines.append(f"    → {r.reasoning}")

    lines.extend([
        f"",
        f"--- Portfolio Summary ---",
        f"  Overall Score:    {portfolio['overall_score']}",
        f"  Confidence:       {portfolio['confidence']}",
        f"  Conviction:       {portfolio['conviction']}",
        f"  Recommendation:   {portfolio['recommendation'].upper()}",
        f"",
        f"Duration: {duration_ms}ms",
        f"========================================",
    ])
    return "\n".join(lines)


def _save_result(result: dict[str, Any]) -> None:
    try:
        with get_db() as session:
            record = AnalysisResult(
                request_id=result["request_id"],
                ticker=result["ticker"],
                status=result["status"],
                overall_score=result["overall_score"],
                confidence=result["confidence"],
                recommendation=result["recommendation"],
                conviction=result["conviction"],
                agent_results=result["agent_results"],
                report=result["report"],
                model_version=result["model_version"],
                data_version=result["data_version"],
                completed_at=datetime.utcnow(),
            )
            session.add(record)
    except Exception as e:
        logger.error("db_save_error", error=str(e))


def _save_audit(
    request_id: str,
    ticker: str,
    agent_results: list[AgentResult],
    total_duration_ms: float,
) -> None:
    try:
        with get_db() as session:
            for r in agent_results:
                log = AuditLog(
                    request_id=request_id,
                    ticker=ticker,
                    agent_name=r.agent_name,
                    action="analysis",
                    details=r.to_dict(),
                    success=not r.metadata.get("fallback", False),
                    duration_ms=total_duration_ms / len(agent_results),
                )
                session.add(log)
    except Exception as e:
        logger.error("audit_save_error", error=str(e))
