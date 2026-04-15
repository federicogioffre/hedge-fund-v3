from celery import Celery
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
    # V7: route slow LLM tasks to a dedicated queue so the primary
    # worker stays responsive. Run a second worker with:
    #   celery -A app.celery_app worker -Q llm_slow --concurrency=2
    task_routes={
        "app.tasks_llm.*": {"queue": "llm_slow"},
    },
    task_queues=None,  # let Celery autocreate queues from routes
)

# Task time/soft limits for LLM tasks are longer: debates can take a while.
celery_app.conf.task_annotations = {
    "app.tasks_llm.generate_tradingagents_signal": {
        "soft_time_limit": 300,
        "time_limit": 420,
    },
}

celery_app.autodiscover_tasks(["app"])
