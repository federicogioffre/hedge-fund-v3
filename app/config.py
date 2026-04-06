from pydantic_settings import BaseSettings
from functools import lru_cache


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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
