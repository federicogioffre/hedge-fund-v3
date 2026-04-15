import math
from typing import Any
from app.agents import AgentResult
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

# Agent weights for signal blending.
# The tradingagents weight is pulled dynamically from settings so operators
# can A/B test without a redeploy.
_BASE_WEIGHTS = {
    "technical": 0.3,
    "sentiment": 0.2,
    "fundamental": 0.3,
    "risk": 0.2,
}

DEFAULT_WEIGHT = 0.1


def _agent_weights() -> dict[str, float]:
    weights = dict(_BASE_WEIGHTS)
    try:
        settings = get_settings()
        if settings.tradingagents_enabled:
            weights["tradingagents"] = float(settings.tradingagents_weight)
    except Exception:
        pass
    return weights


# Kept for backward compatibility with any external import site
AGENT_WEIGHTS = _BASE_WEIGHTS


def blend_signals(signals: list[AgentResult]) -> dict[str, Any]:
    """
    Blend multiple agent signals into a single composite signal.

    Weights:
        technical:   0.3
        sentiment:   0.2
        fundamental: 0.3
        risk:        0.2

    Output:
        score:      weighted average score
        confidence: weighted average confidence
        dispersion: std dev of scores (high → low conviction)
    """
    if not signals:
        return {
            "score": 3.0,
            "confidence": 0.0,
            "dispersion": 0.0,
            "agent_contributions": {},
        }

    total_weight = 0.0
    weighted_score = 0.0
    weighted_confidence = 0.0
    contributions = {}

    weights = _agent_weights()
    for s in signals:
        w = weights.get(s.agent_name, DEFAULT_WEIGHT)
        # Down-weight fallback signals (e.g. TradingAgents cache miss)
        # so they don't dominate when the real signal isn't there yet.
        if s.metadata and s.metadata.get("fallback"):
            w *= 0.25
        weighted_score += s.score * w
        weighted_confidence += s.confidence * w
        total_weight += w
        contributions[s.agent_name] = {
            "score": s.score,
            "weight": round(w, 3),
            "weighted_contribution": round(s.score * w, 3),
        }

    if total_weight == 0:
        total_weight = 1.0

    blended_score = round(weighted_score / total_weight, 3)
    blended_confidence = round(weighted_confidence / total_weight, 3)

    # Dispersion = std dev of individual scores
    scores = [s.score for s in signals]
    mean = sum(scores) / len(scores)
    variance = sum((x - mean) ** 2 for x in scores) / len(scores)
    dispersion = round(math.sqrt(variance), 3)

    result = {
        "score": blended_score,
        "confidence": blended_confidence,
        "dispersion": dispersion,
        "agent_contributions": contributions,
    }

    logger.info(
        "signal_blended",
        score=blended_score,
        confidence=blended_confidence,
        dispersion=dispersion,
        agent_count=len(signals),
    )

    return result
