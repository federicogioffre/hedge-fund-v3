from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://hedgefund:hedgefund@postgres:5432/hedgefund"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_rate_limit: int = 100

    # External APIs
    alpha_vantage_api_key: str = ""
    news_api_key: str = ""
    openai_api_key: str = ""

    # Celery
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # Cache
    cache_ttl: int = 300

    # Logging
    log_level: str = "INFO"

    # --- V6 Trading Engine ---
    trading_mode: Literal["paper", "live"] = "paper"
    initial_capital: float = 100_000.0
    slippage_bps: float = 5.0  # 5 basis points = 0.05%
    rebalance_threshold_pct: float = 2.0  # don't trade if delta < 2%
    max_position_pct: float = 30.0  # max 30% per ticker
    max_daily_loss_pct: float = 5.0  # halt if -5% in a day
    max_drawdown_pct: float = 15.0  # halt if drawdown > 15%

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
