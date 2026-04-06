import math
from typing import Any
from app.agents import AgentResult
from app.logging import get_logger

logger = get_logger(__name__)

# Agent weights for signal blending
AGENT_WEIGHTS = {
    "technical": 0.3,
    "sentiment": 0.2,
    "fundamental": 0.3,
    "risk": 0.2,
}

DEFAULT_WEIGHT = 0.1


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

    for s in signals:
        w = AGENT_WEIGHTS.get(s.agent_name, DEFAULT_WEIGHT)
        weighted_score += s.score * w
        weighted_confidence += s.confidence * w
        total_weight += w
        contributions[s.agent_name] = {
            "score": s.score,
            "weight": w,
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
