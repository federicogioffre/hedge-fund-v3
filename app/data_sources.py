import httpx
from typing import Any
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


async def fetch_market_data(ticker: str) -> dict[str, Any]:
    """Fetch market/price data for a ticker."""
    settings = get_settings()
    try:
        if settings.alpha_vantage_api_key:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    "https://www.alphavantage.co/query",
                    params={
                        "function": "GLOBAL_QUOTE",
                        "symbol": ticker,
                        "apikey": settings.alpha_vantage_api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                quote = data.get("Global Quote", {})
                return {
                    "price": float(quote.get("05. price", 0)),
                    "change_pct": float(
                        quote.get("10. change percent", "0").rstrip("%")
                    ),
                    "volume": int(quote.get("06. volume", 0)),
                    "high": float(quote.get("03. high", 0)),
                    "low": float(quote.get("04. low", 0)),
                    "source": "alpha_vantage",
                }
    except Exception as e:
        logger.warning("market_data_fetch_error", ticker=ticker, error=str(e))

    # Fallback: simulated data
    return _simulated_market_data(ticker)


async def fetch_news_data(ticker: str) -> list[dict[str, Any]]:
    """Fetch recent news for a ticker."""
    settings = get_settings()
    try:
        if settings.news_api_key:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": ticker,
                        "sortBy": "publishedAt",
                        "pageSize": 10,
                        "apiKey": settings.news_api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return [
                    {
                        "title": a["title"],
                        "description": a.get("description", ""),
                        "published_at": a["publishedAt"],
                        "source": a["source"]["name"],
                        "sentiment": None,
                    }
                    for a in data.get("articles", [])
                ]
    except Exception as e:
        logger.warning("news_fetch_error", ticker=ticker, error=str(e))

    return _simulated_news_data(ticker)


async def fetch_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch fundamental data for a ticker."""
    settings = get_settings()
    try:
        if settings.alpha_vantage_api_key:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    "https://www.alphavantage.co/query",
                    params={
                        "function": "OVERVIEW",
                        "symbol": ticker,
                        "apikey": settings.alpha_vantage_api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "pe_ratio": _safe_float(data.get("PERatio")),
                    "eps": _safe_float(data.get("EPS")),
                    "market_cap": _safe_float(data.get("MarketCapitalization")),
                    "dividend_yield": _safe_float(data.get("DividendYield")),
                    "profit_margin": _safe_float(data.get("ProfitMargin")),
                    "revenue_growth": _safe_float(
                        data.get("QuarterlyRevenueGrowthYOY")
                    ),
                    "debt_to_equity": _safe_float(
                        data.get("DebtToEquityRatio")
                    ),
                    "source": "alpha_vantage",
                }
    except Exception as e:
        logger.warning(
            "fundamentals_fetch_error", ticker=ticker, error=str(e)
        )

    return _simulated_fundamentals(ticker)


def _safe_float(val) -> float | None:
    if val is None or val == "None" or val == "-":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _simulated_market_data(ticker: str) -> dict[str, Any]:
    import hashlib

    h = int(hashlib.md5(ticker.encode()).hexdigest()[:8], 16)
    return {
        "price": 100 + (h % 900),
        "change_pct": round(((h % 200) - 100) / 20, 2),
        "volume": 1_000_000 + (h % 9_000_000),
        "high": 100 + (h % 900) + 5,
        "low": 100 + (h % 900) - 5,
        "source": "simulated",
    }


def _simulated_news_data(ticker: str) -> list[dict[str, Any]]:
    return [
        {
            "title": f"{ticker} shows strong quarterly performance",
            "description": "Analysts are optimistic about growth prospects.",
            "published_at": "2024-01-15T10:00:00Z",
            "source": "simulated",
            "sentiment": 0.6,
        },
        {
            "title": f"Market analysis: {ticker} sector outlook",
            "description": "Industry trends suggest continued momentum.",
            "published_at": "2024-01-14T08:00:00Z",
            "source": "simulated",
            "sentiment": 0.4,
        },
    ]


def _simulated_fundamentals(ticker: str) -> dict[str, Any]:
    import hashlib

    h = int(hashlib.md5(ticker.encode()).hexdigest()[:8], 16)
    return {
        "pe_ratio": 10 + (h % 40),
        "eps": round(1 + (h % 20) / 4, 2),
        "market_cap": (h % 500) * 1_000_000_000,
        "dividend_yield": round((h % 50) / 1000, 4),
        "profit_margin": round((h % 30) / 100, 4),
        "revenue_growth": round(((h % 40) - 10) / 100, 4),
        "debt_to_equity": round((h % 200) / 100, 2),
        "source": "simulated",
    }
