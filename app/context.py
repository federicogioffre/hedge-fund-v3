from dataclasses import dataclass, field
from typing import Any, Literal
from datetime import datetime


@dataclass
class AnalysisContext:
    ticker: str
    request_id: str
    asset_type: Literal["equity", "crypto"] = "equity"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "request_id": self.request_id,
            "asset_type": self.asset_type,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "metadata": self.metadata,
        }
