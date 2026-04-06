import asyncio
import time
from datetime import datetime
from typing import Any
from app.data_bundle import DataBundle
from app.agents import AGENTS, PORTFOLIO_AGENT, AgentResult
from app.signal_blender import blend_signals
from app.risk_engine import compute_risk
from app.cache import get_cached_analysis, set_cached_analysis
from app.context import AnalysisContext
from app.version import MODEL_VERSION, DATA_VERSION
from app.db import get_db
from app.models import AnalysisResult, AuditLog
from app.logging import get_logger

logger = get_logger(__name__)


async def run_analysis(ctx: AnalysisContext) -> dict[str, Any]:
    """
    V5 Pipeline: DataBundle → Agents → SignalBlender → RiskEngine → Portfolio → Report
    """
    ticker = ctx.ticker.upper()
    request_id = ctx.request_id
    asset_type = ctx.asset_type

    # Check cache first
    cached = get_cached_analysis(ticker)
    if cached:
        logger.info("using_cached_result", ticker=ticker, request_id=request_id)
        return cached

    start = time.time()
    logger.info(
        "analysis_started",
        ticker=ticker,
        request_id=request_id,
        asset_type=asset_type,
    )

    # 1. Load DataBundle (one load, shared across agents)
    bundle = DataBundle(ticker=ticker, asset_type=asset_type)
    await bundle.load()

    # 2. Run all agents concurrently with return_exceptions=True
    agent_tasks = [agent.safe_analyze(bundle) for agent in AGENTS]
    agent_results_raw = await asyncio.gather(*agent_tasks, return_exceptions=True)

    # Filter out exceptions (safe_analyze should handle them, but belt-and-suspenders)
    agent_results: list[AgentResult] = []
    for r in agent_results_raw:
        if isinstance(r, AgentResult):
            agent_results.append(r)
        else:
            logger.error("agent_gather_exception", error=str(r))

    # 3. Signal Blender
    blended = blend_signals(agent_results)

    # 4. Risk Engine
    risk_metrics = compute_risk(bundle, agent_results)

    # 5. Portfolio agent aggregation
    portfolio = PORTFOLIO_AGENT.analyze_portfolio(agent_results)

    # 6. Build report
    duration_ms = round((time.time() - start) * 1000, 2)
    report = _build_report(
        ticker, asset_type, agent_results, blended, risk_metrics, portfolio, duration_ms
    )

    result = {
        "request_id": request_id,
        "ticker": ticker,
        "asset_type": asset_type,
        "status": "completed",
        "overall_score": portfolio["overall_score"],
        "confidence": portfolio["confidence"],
        "conviction": portfolio["conviction"],
        "recommendation": portfolio["recommendation"],
        "blended_score": blended["score"],
        "dispersion": blended["dispersion"],
        "risk_score": risk_metrics["risk_score"],
        "volatility": risk_metrics["volatility"],
        "var_95": risk_metrics["var_95"],
        "max_drawdown_est": risk_metrics["max_drawdown_est"],
        "agent_results": [r.to_dict() for r in agent_results],
        "signal_blend": blended,
        "risk_metrics": risk_metrics,
        "report": report,
        "model_version": MODEL_VERSION,
        "data_version": DATA_VERSION,
        "duration_ms": duration_ms,
        "completed_at": datetime.utcnow().isoformat(),
    }

    # 7. Save to DB
    _save_result(result)

    # 8. Audit trail
    _save_audit(request_id, ticker, agent_results, duration_ms)

    # 9. Cache result
    set_cached_analysis(ticker, result)

    logger.info(
        "analysis_completed",
        ticker=ticker,
        request_id=request_id,
        score=portfolio["overall_score"],
        blended_score=blended["score"],
        risk_score=risk_metrics["risk_score"],
        conviction=portfolio["conviction"],
        recommendation=portfolio["recommendation"],
        duration_ms=duration_ms,
    )

    return result


def _build_report(
    ticker: str,
    asset_type: str,
    agent_results: list[AgentResult],
    blended: dict[str, Any],
    risk_metrics: dict[str, Any],
    portfolio: dict[str, Any],
    duration_ms: float,
) -> str:
    lines = [
        f"=== Hedge Fund V5 Analysis Report ===",
        f"Ticker: {ticker} ({asset_type})",
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
        f"--- Signal Blend ---",
        f"  Blended Score:    {blended['score']}",
        f"  Blended Conf:     {blended['confidence']}",
        f"  Dispersion:       {blended['dispersion']}",
        f"",
        f"--- Risk Metrics ---",
        f"  Risk Score:       {risk_metrics['risk_score']}",
        f"  Volatility:       {risk_metrics['volatility']}",
        f"  VaR(95%):         {risk_metrics['var_95']}",
        f"  Max Drawdown Est: {risk_metrics['max_drawdown_est']}%",
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
