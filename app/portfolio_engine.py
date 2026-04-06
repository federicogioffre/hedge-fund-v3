from typing import Any
from app.logging import get_logger

logger = get_logger(__name__)


def construct_portfolio(
    rankings: list[dict[str, Any]], capital: float = 100_000.0
) -> dict[str, Any]:
    """
    Construct a portfolio from ranked ticker analysis results.

    Rules:
        - Only bullish tickers (score >= 3.0)
        - Position sizing by score tier
        - Max 10 positions
        - Max 30% per ticker
        - Total allocations capped at 100%

    Position sizing:
        score >= 4.5 → 10%
        score >= 4.0 → 7%
        score >= 3.0 → 5%
        else         → 2%
    """
    # Filter bullish only
    bullish = [
        r for r in rankings
        if r.get("overall_score", 0) >= 3.0
        and r.get("recommendation") not in ("sell", "strong_sell")
    ]

    # Sort by score * confidence descending
    bullish.sort(
        key=lambda x: x.get("overall_score", 0) * x.get("confidence", 0),
        reverse=True,
    )

    # Cap at 10 positions
    bullish = bullish[:10]

    positions = []
    total_allocated_pct = 0.0
    total_risk = 0.0

    for item in bullish:
        score = item.get("overall_score", 3.0)
        confidence = item.get("confidence", 0.5)
        conviction = item.get("conviction", 0.0)
        risk_score = item.get("risk_score", 0.3)

        # Position sizing by score tier
        if score >= 4.5:
            size_pct = 10.0
        elif score >= 4.0:
            size_pct = 7.0
        elif score >= 3.0:
            size_pct = 5.0
        else:
            size_pct = 2.0

        # Cap at 30% per ticker
        size_pct = min(size_pct, 30.0)

        # Don't exceed 100%
        if total_allocated_pct + size_pct > 100.0:
            size_pct = 100.0 - total_allocated_pct

        if size_pct <= 0:
            break

        allocation = round(capital * size_pct / 100.0, 2)
        total_allocated_pct += size_pct
        total_risk += risk_score * (size_pct / 100.0)

        positions.append({
            "ticker": item.get("ticker", "UNKNOWN"),
            "score": score,
            "confidence": confidence,
            "conviction": conviction,
            "size_pct": round(size_pct, 2),
            "allocation": allocation,
            "risk_score": risk_score,
        })

    cash = round(capital * (1 - total_allocated_pct / 100.0), 2)

    # Expected return estimate: weighted average of (score - 3) * 2% per position
    expected_return = 0.0
    for p in positions:
        weight = p["size_pct"] / 100.0
        expected_return += (p["score"] - 3.0) * 0.02 * weight

    result = {
        "positions": positions,
        "position_count": len(positions),
        "total_allocated_pct": round(total_allocated_pct, 2),
        "cash": cash,
        "cash_pct": round(100.0 - total_allocated_pct, 2),
        "expected_return": round(expected_return * 100, 3),
        "portfolio_risk": round(total_risk, 4),
        "capital": capital,
    }

    logger.info(
        "portfolio_constructed",
        positions=len(positions),
        allocated_pct=total_allocated_pct,
        cash=cash,
        expected_return=result["expected_return"],
    )

    return result
