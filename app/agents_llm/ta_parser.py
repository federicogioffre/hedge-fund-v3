"""
Deterministic parser that maps a TradingAgents output payload to the
hedge-fund-v3 AgentResult contract (score 1-5, confidence 0-1, risk 0-1).

Input shape (best-effort, tolerant to missing fields):
    {
        "decision": "BUY" | "STRONG_BUY" | "HOLD" | "SELL" | "STRONG_SELL",
        "confidence": 0..1,              # optional
        "bull_arguments": [str],         # optional
        "bear_arguments": [str],         # optional
        "risk_assessment": {
            "level": "low" | "medium" | "high" | "extreme",
            "notes": str,
        },
        "trader_summary": str,           # optional
        "transcript": str | list[dict],  # optional (full debate)
        "model": str,                    # provider model id
        "raw": Any,                      # anything else upstream returned
    }

Output: dict compatible with AgentResult.__init__ kwargs.
"""

from __future__ import annotations

from typing import Any

# Map textual decisions to a base score (1..5 scale)
_DECISION_SCORE = {
    "strong_buy": 4.7,
    "buy": 4.0,
    "accumulate": 3.7,
    "hold": 3.0,
    "neutral": 3.0,
    "reduce": 2.3,
    "sell": 2.0,
    "strong_sell": 1.3,
}

# Risk level → normalized risk 0..1
_RISK_LEVEL = {
    "low": 0.2,
    "medium": 0.4,
    "moderate": 0.4,
    "high": 0.65,
    "extreme": 0.9,
    "severe": 0.9,
}


def _norm_decision(raw: Any) -> str:
    if not raw:
        return "hold"
    token = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    # Collapse common variants
    if token in ("strongbuy",):
        token = "strong_buy"
    if token in ("strongsell",):
        token = "strong_sell"
    return token


def _norm_risk_level(raw: Any) -> str:
    if not raw:
        return "medium"
    return str(raw).strip().lower()


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def parse_tradingagents_output(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize a TradingAgents result into AgentResult kwargs.
    Always returns a valid dict (never raises on malformed input).
    """
    if not isinstance(payload, dict):
        payload = {}

    decision = _norm_decision(payload.get("decision"))
    base_score = _DECISION_SCORE.get(decision, 3.0)

    bulls = payload.get("bull_arguments") or []
    bears = payload.get("bear_arguments") or []
    bull_count = len(bulls) if isinstance(bulls, list) else 0
    bear_count = len(bears) if isinstance(bears, list) else 0

    # Debate skew: more arguments on one side nudges the score slightly
    # (bounded so it cannot override the headline decision)
    total_args = bull_count + bear_count
    if total_args > 0:
        skew = (bull_count - bear_count) / total_args  # -1..1
        base_score = _clip(base_score + 0.3 * skew, 1.0, 5.0)

    # Confidence: explicit > debate consensus > default 0.5
    explicit_conf = payload.get("confidence")
    if isinstance(explicit_conf, (int, float)):
        confidence = _clip(float(explicit_conf), 0.0, 1.0)
    elif total_args > 0:
        # Consensus strength = |bull - bear| / total
        consensus = abs(bull_count - bear_count) / total_args
        confidence = _clip(0.4 + 0.4 * consensus, 0.0, 1.0)
    else:
        confidence = 0.5

    # Risk from explicit assessment, else derived from decision extremity
    risk_block = payload.get("risk_assessment") or {}
    level = _norm_risk_level(risk_block.get("level"))
    if level in _RISK_LEVEL:
        risk = _RISK_LEVEL[level]
    else:
        # Fallback: extreme decisions are riskier; hold is moderate
        if decision in ("strong_buy", "strong_sell"):
            risk = 0.55
        elif decision in ("buy", "sell"):
            risk = 0.4
        else:
            risk = 0.35

    # Reasoning: prefer trader_summary, else synthesize from debate
    trader_summary = payload.get("trader_summary")
    if isinstance(trader_summary, str) and trader_summary.strip():
        reasoning = trader_summary.strip()
    else:
        parts: list[str] = [f"decision={decision.upper()}"]
        if bull_count:
            parts.append(f"bulls={bull_count}")
        if bear_count:
            parts.append(f"bears={bear_count}")
        notes = risk_block.get("notes") if isinstance(risk_block, dict) else None
        if notes:
            parts.append(f"risk={str(notes)[:120]}")
        reasoning = "; ".join(parts)

    # Truncate reasoning to keep DB payloads reasonable
    if len(reasoning) > 500:
        reasoning = reasoning[:497] + "..."

    metadata: dict[str, Any] = {
        "source": "tradingagents",
        "decision": decision,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "risk_level": level,
        "model": payload.get("model"),
    }
    # Attach debate transcript if small enough for audit
    transcript = payload.get("transcript")
    if transcript is not None:
        s = transcript if isinstance(transcript, str) else str(transcript)
        metadata["transcript_excerpt"] = s[:2000]

    return {
        "agent_name": "tradingagents",
        "score": round(float(base_score), 2),
        "confidence": round(float(confidence), 3),
        "risk": round(float(risk), 3),
        "reasoning": reasoning,
        "metadata": metadata,
    }
