import math
from typing import Any
from app.logging import get_logger

logger = get_logger(__name__)


def compute_signal_momentum(signal_history: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Compute temporal signal metrics from recent signal history.

    Uses last 3-5 records:
        momentum:     mean of score deltas (trend direction)
        acceleration: most recent delta (rate of change)
        stability:    std dev of scores (lower = more stable)
    """
    if not signal_history or len(signal_history) < 2:
        result = {
            "momentum": 0.0,
            "acceleration": 0.0,
            "stability": 1.0,
        }
        logger.info("momentum_computed", result="insufficient_data")
        return result

    # Extract scores, ordered newest-first from DB, reverse for chronological
    scores = [h.get("score", 3.0) for h in reversed(signal_history)]

    # Use last 5 max
    scores = scores[-5:]

    # Deltas between consecutive scores
    deltas = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]

    # Momentum = mean of deltas
    momentum = sum(deltas) / len(deltas) if deltas else 0.0

    # Acceleration = most recent delta
    acceleration = deltas[-1] if deltas else 0.0

    # Stability = std dev of scores (lower = more stable)
    mean_score = sum(scores) / len(scores)
    variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
    stability = math.sqrt(variance)

    result = {
        "momentum": round(momentum, 4),
        "acceleration": round(acceleration, 4),
        "stability": round(stability, 4),
    }

    logger.info(
        "momentum_computed",
        momentum=result["momentum"],
        acceleration=result["acceleration"],
        stability=result["stability"],
        sample_count=len(scores),
    )

    return result


def apply_temporal_adjustment(
    score: float,
    confidence: float,
    temporal_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Adjust score and confidence based on temporal signal data.

    - momentum > 0 → boost score
    - acceleration > 0 → boost confidence
    - high instability → reduce confidence
    """
    momentum = temporal_data.get("momentum", 0.0)
    acceleration = temporal_data.get("acceleration", 0.0)
    stability = temporal_data.get("stability", 0.0)

    # Score adjustment: momentum * 0.5
    adjusted_score = score + momentum * 0.5
    adjusted_score = max(1.0, min(5.0, adjusted_score))

    # Confidence boost from positive acceleration
    adjusted_confidence = confidence
    if acceleration > 0:
        adjusted_confidence *= (1 + acceleration * 0.2)

    # Confidence penalty from instability
    if stability > 0:
        adjusted_confidence *= max(0.3, 1.0 - stability * 0.3)

    adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))

    result = {
        "adjusted_score": round(adjusted_score, 3),
        "adjusted_confidence": round(adjusted_confidence, 3),
        "original_score": score,
        "original_confidence": confidence,
        "momentum": momentum,
        "acceleration": acceleration,
        "stability": stability,
    }

    logger.info(
        "temporal_adjustment_applied",
        original_score=score,
        adjusted_score=result["adjusted_score"],
        original_confidence=confidence,
        adjusted_confidence=result["adjusted_confidence"],
        momentum=momentum,
    )

    return result
