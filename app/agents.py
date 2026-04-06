import time
from abc import ABC, abstractmethod
from typing import Any
from app.data_bundle import DataBundle
from app.logging import get_logger

logger = get_logger(__name__)

FALLBACK_SCORE = 3.0


class AgentResult:
    def __init__(
        self,
        agent_name: str,
        score: float,
        confidence: float,
        risk: float,
        reasoning: str,
        metadata: dict[str, Any] | None = None,
    ):
        self.agent_name = agent_name
        self.score = max(1.0, min(5.0, score))  # clamp 1-5
        self.confidence = max(0.0, min(1.0, confidence))  # clamp 0-1
        self.risk = max(0.0, min(1.0, risk))  # clamp 0-1
        self.reasoning = reasoning
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "score": self.score,
            "confidence": self.confidence,
            "risk": self.risk,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
        }


class BaseAgent(ABC):
    name: str = "base"

    @abstractmethod
    async def analyze(self, bundle: DataBundle) -> AgentResult:
        pass

    async def safe_analyze(self, bundle: DataBundle) -> AgentResult:
        start = time.time()
        try:
            result = await self.analyze(bundle)
            duration = (time.time() - start) * 1000
            logger.info(
                "agent_completed",
                agent=self.name,
                ticker=bundle.ticker,
                score=result.score,
                duration_ms=round(duration, 2),
            )
            return result
        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.error(
                "agent_failed",
                agent=self.name,
                ticker=bundle.ticker,
                error=str(e),
                duration_ms=round(duration, 2),
            )
            return AgentResult(
                agent_name=self.name,
                score=FALLBACK_SCORE,
                confidence=0.3,
                risk=0.5,
                reasoning=f"Agent failed with fallback score: {e}",
                metadata={"fallback": True, "error": str(e)},
            )


class TechnicalAgent(BaseAgent):
    name = "technical"

    async def analyze(self, bundle: DataBundle) -> AgentResult:
        market = bundle.market
        change_pct = market.get("change_pct", 0)
        volume = market.get("volume", 0)

        # Simple momentum scoring
        if change_pct > 3:
            score = 4.5
        elif change_pct > 1:
            score = 4.0
        elif change_pct > -1:
            score = 3.0
        elif change_pct > -3:
            score = 2.0
        else:
            score = 1.5

        volume_signal = min(volume / 5_000_000, 1.0)
        confidence = 0.5 + volume_signal * 0.3
        risk = 0.3 if abs(change_pct) < 2 else 0.6

        return AgentResult(
            agent_name=self.name,
            score=score,
            confidence=confidence,
            risk=risk,
            reasoning=f"Price change {change_pct}%, volume {volume:,}",
            metadata={"change_pct": change_pct, "volume": volume},
        )


class FundamentalAgent(BaseAgent):
    name = "fundamental"

    async def analyze(self, bundle: DataBundle) -> AgentResult:
        f = bundle.fundamentals
        pe = f.get("pe_ratio")
        eps = f.get("eps")
        margin = f.get("profit_margin")
        growth = f.get("revenue_growth")

        score = 3.0
        reasons = []

        if pe is not None:
            if pe < 15:
                score += 0.5
                reasons.append(f"Low P/E ({pe})")
            elif pe > 30:
                score -= 0.5
                reasons.append(f"High P/E ({pe})")

        if eps is not None and eps > 3:
            score += 0.3
            reasons.append(f"Strong EPS ({eps})")

        if margin is not None and margin > 0.15:
            score += 0.3
            reasons.append(f"Good margins ({margin:.1%})")

        if growth is not None and growth > 0.1:
            score += 0.4
            reasons.append(f"Revenue growth ({growth:.1%})")

        confidence = 0.7 if pe is not None else 0.4
        risk = 0.4

        return AgentResult(
            agent_name=self.name,
            score=score,
            confidence=confidence,
            risk=risk,
            reasoning="; ".join(reasons) if reasons else "Neutral fundamentals",
            metadata={"pe_ratio": pe, "eps": eps},
        )


class SentimentAgent(BaseAgent):
    name = "sentiment"

    async def analyze(self, bundle: DataBundle) -> AgentResult:
        news = bundle.news
        if not news:
            return AgentResult(
                agent_name=self.name,
                score=3.0,
                confidence=0.3,
                risk=0.5,
                reasoning="No news data available",
            )

        sentiments = [
            n.get("sentiment", 0) for n in news if n.get("sentiment") is not None
        ]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0

        # Map sentiment (-1 to 1) to score (1 to 5)
        score = 3.0 + avg_sentiment * 2.0
        confidence = min(0.3 + len(news) * 0.05, 0.8)
        risk = 0.5 - avg_sentiment * 0.2

        return AgentResult(
            agent_name=self.name,
            score=score,
            confidence=confidence,
            risk=risk,
            reasoning=f"Avg sentiment: {avg_sentiment:.2f} from {len(news)} articles",
            metadata={
                "avg_sentiment": avg_sentiment,
                "article_count": len(news),
            },
        )


class RiskAgent(BaseAgent):
    name = "risk"

    async def analyze(self, bundle: DataBundle) -> AgentResult:
        market = bundle.market
        f = bundle.fundamentals

        risk_factors = []
        risk_score = 0.0

        change_pct = abs(market.get("change_pct", 0))
        if change_pct > 5:
            risk_score += 0.3
            risk_factors.append(f"High volatility ({change_pct}%)")

        dte = f.get("debt_to_equity")
        if dte is not None and dte > 1.5:
            risk_score += 0.2
            risk_factors.append(f"High debt/equity ({dte})")

        margin = f.get("profit_margin")
        if margin is not None and margin < 0.05:
            risk_score += 0.2
            risk_factors.append(f"Low margins ({margin:.1%})")

        risk = min(risk_score, 1.0)
        # Higher risk -> lower score
        score = 5.0 - risk * 4.0
        confidence = 0.6

        return AgentResult(
            agent_name=self.name,
            score=score,
            confidence=confidence,
            risk=risk,
            reasoning="; ".join(risk_factors) if risk_factors else "Low risk profile",
            metadata={"risk_factors": risk_factors},
        )


class PortfolioAgent(BaseAgent):
    """Computes conviction and recommendation from aggregated agent results."""

    name = "portfolio"

    async def analyze(self, bundle: DataBundle) -> AgentResult:
        raise NotImplementedError("Use analyze_portfolio instead")

    def analyze_portfolio(
        self, agent_results: list[AgentResult]
    ) -> dict[str, Any]:
        if not agent_results:
            return {
                "overall_score": FALLBACK_SCORE,
                "confidence": 0.3,
                "conviction": 0.0,
                "recommendation": "hold",
            }

        total_weight = sum(r.confidence for r in agent_results)
        if total_weight == 0:
            total_weight = 1.0

        weighted_score = sum(r.score * r.confidence for r in agent_results)
        overall_score = round(weighted_score / total_weight, 2)

        avg_confidence = sum(r.confidence for r in agent_results) / len(
            agent_results
        )
        avg_risk = sum(r.risk for r in agent_results) / len(agent_results)

        # conviction = score * confidence * (1 - risk)
        conviction = round(
            overall_score * avg_confidence * (1 - avg_risk), 2
        )

        if overall_score >= 4.0 and conviction >= 1.5:
            recommendation = "strong_buy"
        elif overall_score >= 3.5:
            recommendation = "buy"
        elif overall_score >= 2.5:
            recommendation = "hold"
        elif overall_score >= 2.0:
            recommendation = "sell"
        else:
            recommendation = "strong_sell"

        return {
            "overall_score": overall_score,
            "confidence": round(avg_confidence, 2),
            "risk": round(avg_risk, 2),
            "conviction": conviction,
            "recommendation": recommendation,
        }


# Agent registry
AGENTS: list[BaseAgent] = [
    TechnicalAgent(),
    FundamentalAgent(),
    SentimentAgent(),
    RiskAgent(),
]

PORTFOLIO_AGENT = PortfolioAgent()
