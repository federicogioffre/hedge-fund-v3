from typing import Any
from app.data_bundle import DataBundle
from app.agents import AgentResult
from app.logging import get_logger

logger = get_logger(__name__)


def compute_risk(
    bundle: DataBundle,
    signals: list[AgentResult],
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compute risk metrics for a ticker.

    - volatility from market_snapshot
    - VaR(95%) ≈ volatility * 1.65
    - penalizes leverage and high volatility
    """
    market = bundle.market
    fundamentals = bundle.fundamentals

    # Base volatility from market data
    volatility = market.get("volatility", abs(market.get("change_pct", 2.0)))
    if volatility == 0:
        volatility = 1.0

    # Normalize volatility to 0-1 scale (10% daily move = 1.0)
    vol_normalized = min(volatility / 10.0, 1.0)

    # VaR 95% approximation: volatility * z-score(95%)
    var_95 = round(volatility * 1.65, 4)

    # Max drawdown estimate: heuristic based on volatility
    max_drawdown_est = round(min(volatility * 3.0, 50.0), 2)

    # Risk score computation (0-1)
    risk_score = vol_normalized * 0.5

    # Penalize high debt
    dte = fundamentals.get("debt_to_equity")
    if dte is not None and dte > 1.5:
        risk_score += 0.15

    # Penalize low margins
    margin = fundamentals.get("profit_margin")
    if margin is not None and margin < 0.05:
        risk_score += 0.1

    # Penalize high agent dispersion (disagreement = uncertainty)
    if signals:
        scores = [s.score for s in signals]
        mean = sum(scores) / len(scores)
        dispersion = (sum((x - mean) ** 2 for x in scores) / len(scores)) ** 0.5
        risk_score += dispersion * 0.1

    # Leverage penalty
    if portfolio_context:
        leverage = portfolio_context.get("leverage", 1.0)
        if leverage > 1.0:
            risk_score += (leverage - 1.0) * 0.2

    # Crypto penalty
    if bundle.asset_type == "crypto":
        risk_score += 0.15

    risk_score = round(min(risk_score, 1.0), 3)

    result = {
        "risk_score": risk_score,
        "volatility": round(volatility, 4),
        "max_drawdown_est": max_drawdown_est,
        "var_95": var_95,
        "asset_type": bundle.asset_type,
    }

    logger.info(
        "risk_computed",
        ticker=bundle.ticker,
        risk_score=risk_score,
        volatility=volatility,
        var_95=var_95,
    )

    return result
