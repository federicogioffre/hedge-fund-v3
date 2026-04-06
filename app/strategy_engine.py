from typing import Any
from app.logging import get_logger

logger = get_logger(__name__)

# Base strategy weights
BASE_WEIGHTS = {
    "momentum": 0.5,
    "mean_reversion": 0.3,
    "defensive": 0.2,
}


def blend_strategy(
    score: float,
    confidence: float,
    regime: dict[str, Any],
    risk_score: float = 0.3,
) -> dict[str, Any]:
    """
    Dynamically blend strategy weights based on regime and volatility.

    Adjustments:
        bull + low_vol   → boost momentum, reduce defensive
        bear + any       → boost defensive, reduce momentum
        sideways         → boost mean_reversion
        high_vol         → boost defensive, reduce momentum
    """
    weights = dict(BASE_WEIGHTS)
    market_regime = regime.get("market_regime", "sideways")
    vol_regime = regime.get("vol_regime", "low_vol")

    # Regime adjustments
    if market_regime == "bull":
        weights["momentum"] += 0.15
        weights["defensive"] -= 0.1
        weights["mean_reversion"] -= 0.05
    elif market_regime == "bear":
        weights["momentum"] -= 0.2
        weights["defensive"] += 0.15
        weights["mean_reversion"] += 0.05
    else:  # sideways
        weights["mean_reversion"] += 0.1
        weights["momentum"] -= 0.05
        weights["defensive"] -= 0.05

    # Volatility adjustments
    if vol_regime == "high_vol":
        weights["defensive"] += 0.1
        weights["momentum"] -= 0.1

    # Clamp weights to [0, 1]
    for k in weights:
        weights[k] = max(0.0, min(1.0, weights[k]))

    # Normalize weights to sum to 1
    total = sum(weights.values())
    if total > 0:
        weights = {k: round(v / total, 3) for k, v in weights.items()}

    # Compute strategy sub-scores
    # Momentum strategy: rewards high score
    momentum_score = score
    # Mean reversion: rewards scores near 3 (neutral), penalizes extremes
    mean_rev_score = 5.0 - abs(score - 3.0) * 1.5
    mean_rev_score = max(1.0, min(5.0, mean_rev_score))
    # Defensive: inversely proportional to risk
    defensive_score = 5.0 - risk_score * 4.0
    defensive_score = max(1.0, min(5.0, defensive_score))

    adjusted_score = (
        weights["momentum"] * momentum_score
        + weights["mean_reversion"] * mean_rev_score
        + weights["defensive"] * defensive_score
    )
    adjusted_score = round(max(1.0, min(5.0, adjusted_score)), 3)

    result = {
        "adjusted_score": adjusted_score,
        "strategy_weights": weights,
        "sub_scores": {
            "momentum": round(momentum_score, 3),
            "mean_reversion": round(mean_rev_score, 3),
            "defensive": round(defensive_score, 3),
        },
        "regime": market_regime,
        "vol_regime": vol_regime,
    }

    logger.info(
        "strategy_blended",
        adjusted_score=adjusted_score,
        regime=market_regime,
        vol_regime=vol_regime,
        weights=weights,
    )

    return result
