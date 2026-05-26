from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "hedge_fund_v3",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    task_soft_time_limit=120,
    task_time_limit=180,
    task_routes={
        "app.tasks_llm.*": {"queue": "llm_slow"},
    },
    task_queues=None,
    beat_schedule={
        "daily-report": {
            "task": "app.tasks_reporting.send_daily_report",
            "schedule": crontab(
                hour=settings.report_hour_utc,
                minute=settings.report_minute_utc,
            ),
        },
    },
)

# Task time/soft limits for LLM tasks are longer: debates can take a while.
celery_app.conf.task_annotations = {
    "app.tasks_llm.generate_tradingagents_signal": {
        "soft_time_limit": 300,
        "time_limit": 420,
    },
}

celery_app.conf.include = [
    "app.tasks",
    "app.tasks_reporting",
    "app.tasks_llm",
]
