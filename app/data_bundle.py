from dataclasses import dataclass, field
from typing import Any
from app.data_sources import fetch_market_data, fetch_news_data, fetch_fundamentals
from app.version import DATA_VERSION
from app.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DataBundle:
    """Loads market/news/fundamentals ONCE and shares across agents."""

    ticker: str
    market: dict[str, Any] = field(default_factory=dict)
    news: list[dict[str, Any]] = field(default_factory=list)
    fundamentals: dict[str, Any] = field(default_factory=dict)
    version: str = DATA_VERSION
    _loaded: bool = field(default=False, repr=False)

    async def load(self) -> "DataBundle":
        if self._loaded:
            return self
        logger.info("data_bundle_loading", ticker=self.ticker)
        import asyncio

        market_task = asyncio.create_task(fetch_market_data(self.ticker))
        news_task = asyncio.create_task(fetch_news_data(self.ticker))
        fundamentals_task = asyncio.create_task(
            fetch_fundamentals(self.ticker)
        )

        self.market, self.news, self.fundamentals = await asyncio.gather(
            market_task, news_task, fundamentals_task
        )
        self._loaded = True
        logger.info("data_bundle_loaded", ticker=self.ticker)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "market": self.market,
            "news": self.news,
            "fundamentals": self.fundamentals,
            "version": self.version,
        }
