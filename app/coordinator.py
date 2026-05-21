import asyncio
import time
from datetime import datetime
from typing import Any
from app.data_bundle import DataBundle
from app.agents import AGENTS, PORTFOLIO_AGENT, AgentResult
from app.signal_blender import blend_signals
from app.signal_temporal import compute_signal_momentum, apply_temporal_adjustment
from app.risk_engine import compute_risk
from app.regime import detect_regime
from app.strategy_engine import blend_strategy
from app.cache import get_cached_analysis, set_cached_analysis
from app.context import AnalysisContext
from app.version import MODEL_VERSION, DATA_VERSION
from app.db import get_db, get_recent_signal_history
from app.models import AnalysisResult, AuditLog, SignalHistory, Snapshot
from app.logging import get_logger

logger = get_logger(__name__)


async def run_analysis(ctx: AnalysisContext) -> dict[str, Any]:
    """
    V5.1 Pipeline:
        1. DataBundle
        2. Agents (with timeout)
        3. Load SignalHistory → Temporal adjustment
        4. Signal Blender
        5. Regime Detection
        6. Risk Engine
        7. Strategy Blending
        8. Portfolio Agent
        9. Final Report
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

    agent_results: list[AgentResult] = []
    for r in agent_results_raw:
        if isinstance(r, AgentResult):
            agent_results.append(r)
        else:
            logger.error("agent_gather_exception", error=str(r))

    # 3. Load SignalHistory + Temporal adjustment
    temporal_data = {"momentum": 0.0, "acceleration": 0.0, "stability": 0.0}
    try:
        with get_db() as session:
            # Aggregate history across all agents for this ticker
            all_history = []
            for agent in AGENTS:
                history = get_recent_signal_history(
                    session, ticker, agent.name, limit=5
                )
                all_history.extend(history)

            if all_history:
                temporal_data = compute_signal_momentum(all_history)
    except Exception as e:
        logger.warning("signal_history_load_error", error=str(e))

    # Apply temporal adjustment to each agent result
    adjusted_results = []
    for r in agent_results:
        adj = apply_temporal_adjustment(r.score, r.confidence, temporal_data)
        adjusted_r = AgentResult(
            agent_name=r.agent_name,
            score=adj["adjusted_score"],
            confidence=adj["adjusted_confidence"],
            risk=r.risk,
            reasoning=r.reasoning,
            metadata={
                **r.metadata,
                "temporal_adjusted": True,
                "original_score": r.score,
                "original_confidence": r.confidence,
            },
        )
        adjusted_results.append(adjusted_r)

    # 4. Signal Blender (on adjusted results)
    blended = blend_signals(adjusted_results)

    # 5. Regime Detection
    regime = detect_regime(bundle)

    # 6. Risk Engine
    risk_metrics = compute_risk(bundle, adjusted_results)

    # 7. Strategy Blending
    strategy = blend_strategy(
        score=blended["score"],
        confidence=blended["confidence"],
        regime=regime,
        risk_score=risk_metrics["risk_score"],
    )

    # 8. Portfolio agent aggregation
    portfolio = PORTFOLIO_AGENT.analyze_portfolio(adjusted_results)

    # Enhanced conviction: adjusted_score * adjusted_confidence * (1 - risk) * (1 + momentum)
    momentum = temporal_data.get("momentum", 0.0)
    conviction = round(
        strategy["adjusted_score"]
        * blended["confidence"]
        * (1 - risk_metrics["risk_score"])
        * (1 + max(-0.5, min(0.5, momentum))),  # clamp momentum effect
        3,
    )

    # 9. Build report
    duration_ms = round((time.time() - start) * 1000, 2)
    report = _build_report(
        ticker, asset_type, agent_results, adjusted_results,
        blended, temporal_data, regime, risk_metrics, strategy,
        portfolio, conviction, duration_ms,
    )

    result = {
        "request_id": request_id,
        "ticker": ticker,
        "asset_type": asset_type,
        "status": "completed",
        "overall_score": portfolio["overall_score"],
        "confidence": portfolio["confidence"],
        "conviction": conviction,
        "recommendation": portfolio["recommendation"],
        "blended_score": blended["score"],
        "strategy_score": strategy["adjusted_score"],
        "dispersion": blended["dispersion"],
        "risk_score": risk_metrics["risk_score"],
        "volatility": risk_metrics["volatility"],
        "var_95": risk_metrics["var_95"],
        "max_drawdown_est": risk_metrics["max_drawdown_est"],
        "momentum": temporal_data["momentum"],
        "acceleration": temporal_data["acceleration"],
        "stability": temporal_data["stability"],
        "regime": regime,
        "strategy": strategy,
        "agent_results": [r.to_dict() for r in agent_results],
        "adjusted_agent_results": [r.to_dict() for r in adjusted_results],
        "signal_blend": blended,
        "risk_metrics": risk_metrics,
        "temporal_data": temporal_data,
        "report": report,
        "model_version": MODEL_VERSION,
        "data_version": DATA_VERSION,
        "duration_ms": duration_ms,
        "completed_at": datetime.utcnow().isoformat(),
    }

    # 10. Save to DB
    _save_result(result)

    # 11. Save signal history
    _save_signal_history(request_id, ticker, adjusted_results, temporal_data)

    # 12. Save snapshot
    _save_snapshot(ticker, bundle, result)

    # 13. Audit trail
    _save_audit(request_id, ticker, agent_results, duration_ms)

    # 14. Cache result
    set_cached_analysis(ticker, result)

    logger.info(
        "analysis_completed",
        ticker=ticker,
        request_id=request_id,
        score=portfolio["overall_score"],
        blended_score=blended["score"],
        strategy_score=strategy["adjusted_score"],
        risk_score=risk_metrics["risk_score"],
        conviction=conviction,
        momentum=temporal_data["momentum"],
        regime=regime["market_regime"],
        recommendation=portfolio["recommendation"],
        duration_ms=duration_ms,
    )

    return result


def _build_report(
    ticker: str,
    asset_type: str,
    raw_results: list[AgentResult],
    adjusted_results: list[AgentResult],
    blended: dict[str, Any],
    temporal: dict[str, Any],
    regime: dict[str, Any],
    risk_metrics: dict[str, Any],
    strategy: dict[str, Any],
    portfolio: dict[str, Any],
    conviction: float,
    duration_ms: float,
) -> str:
    lines = [
        f"=== Hedge Fund V5.1 Analysis Report ===",
        f"Ticker: {ticker} ({asset_type})",
        f"Model: {MODEL_VERSION} | Data: {DATA_VERSION}",
        f"",
        f"--- Agent Scores (raw → adjusted) ---",
    ]
    for raw, adj in zip(raw_results, adjusted_results):
        fallback = " [FALLBACK]" if raw.metadata.get("fallback") else ""
        lines.append(
            f"  {raw.agent_name:15s}: {raw.score:.1f}→{adj.score:.1f}  "
            f"conf={raw.confidence:.2f}→{adj.confidence:.2f}  "
            f"risk={raw.risk:.2f}{fallback}"
        )
        lines.append(f"    → {raw.reasoning}")

    lines.extend([
        f"",
        f"--- Temporal Intelligence ---",
        f"  Momentum:         {temporal['momentum']}",
        f"  Acceleration:     {temporal['acceleration']}",
        f"  Stability:        {temporal['stability']}",
        f"",
        f"--- Signal Blend ---",
        f"  Blended Score:    {blended['score']}",
        f"  Blended Conf:     {blended['confidence']}",
        f"  Dispersion:       {blended['dispersion']}",
        f"",
        f"--- Regime ---",
        f"  Market:           {regime['market_regime']}",
        f"  Volatility:       {regime['vol_regime']}",
        f"",
        f"--- Strategy ---",
        f"  Strategy Score:   {strategy['adjusted_score']}",
        f"  Weights:          {strategy['strategy_weights']}",
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
        f"  Conviction:       {conviction}",
        f"  Recommendation:   {portfolio['recommendation'].upper()}",
        f"",
        f"Duration: {duration_ms}ms",
        f"========================================",
    ])
    return "\n".join(lines)


def _save_result(result: dict[str, Any]) -> None:
    # The Celery task layer already inserts a "processing" row with this
    # request_id at task start (see app/tasks.py:analyze_ticker), so we
    # cannot blindly INSERT again - request_id has a UNIQUE index.
    # Look up the existing row and update it; fall back to INSERT if the
    # task-level pending write failed for any reason.
    try:
        with get_db() as session:
            record = (
                session.query(AnalysisResult)
                .filter_by(request_id=result["request_id"])
                .first()
            )
            if record is None:
                record = AnalysisResult(request_id=result["request_id"])
                session.add(record)
            record.ticker = result["ticker"]
            record.status = result["status"]
            record.overall_score = result["overall_score"]
            record.confidence = result["confidence"]
            record.recommendation = result["recommendation"]
            record.conviction = result["conviction"]
            record.agent_results = result["agent_results"]
            record.report = result["report"]
            record.model_version = result["model_version"]
            record.data_version = result["data_version"]
            record.completed_at = datetime.utcnow()
    except Exception as e:
        logger.error("db_save_error", error=str(e))


def _save_signal_history(
    request_id: str,
    ticker: str,
    agent_results: list[AgentResult],
    temporal_data: dict[str, Any],
) -> None:
    try:
        with get_db() as session:
            for r in agent_results:
                record = SignalHistory(
                    ticker=ticker,
                    agent_name=r.agent_name,
                    score=r.score,
                    confidence=r.confidence,
                    risk=r.risk,
                    momentum=temporal_data.get("momentum"),
                    acceleration=temporal_data.get("acceleration"),
                    request_id=request_id,
                )
                session.add(record)
    except Exception as e:
        logger.error("signal_history_save_error", error=str(e))


def _save_snapshot(
    ticker: str,
    bundle: DataBundle,
    result: dict[str, Any],
) -> None:
    try:
        with get_db() as session:
            snapshot = Snapshot(
                ticker=ticker,
                horizon="default",
                data_json={
                    "bundle": bundle.to_dict(),
                    "blended_score": result.get("blended_score"),
                    "risk_score": result.get("risk_score"),
                    "conviction": result.get("conviction"),
                    "regime": result.get("regime"),
                },
                model_version=MODEL_VERSION,
            )
            session.add(snapshot)
    except Exception as e:
        logger.error("snapshot_save_error", error=str(e))


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
