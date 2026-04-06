import json
import redis
from typing import Any
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_redis_client = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(
            settings.redis_url, decode_responses=True
        )
    return _redis_client


def make_cache_key(ticker: str) -> str:
    return f"analysis:{ticker.upper()}"


def get_cached_analysis(ticker: str) -> dict[str, Any] | None:
    try:
        r = get_redis()
        key = make_cache_key(ticker)
        data = r.get(key)
        if data:
            logger.info("cache_hit", ticker=ticker)
            return json.loads(data)
    except Exception as e:
        logger.warning("cache_read_error", ticker=ticker, error=str(e))
    return None


def set_cached_analysis(ticker: str, result: dict[str, Any]) -> None:
    try:
        settings = get_settings()
        r = get_redis()
        key = make_cache_key(ticker)
        r.setex(key, settings.cache_ttl, json.dumps(result, default=str))
        logger.info("cache_set", ticker=ticker, ttl=settings.cache_ttl)
    except Exception as e:
        logger.warning("cache_write_error", ticker=ticker, error=str(e))


def invalidate_cache(ticker: str) -> None:
    try:
        r = get_redis()
        key = make_cache_key(ticker)
        r.delete(key)
        logger.info("cache_invalidated", ticker=ticker)
    except Exception as e:
        logger.warning("cache_invalidate_error", ticker=ticker, error=str(e))
