import logging

import structlog

from app.config import get_settings


def setup_logging():
    settings = get_settings()
    # structlog.make_filtering_bound_logger takes a numeric level (same
    # scale as stdlib logging). Resolve the name through logging so the
    # call works against any structlog version - earlier drafts of this
    # file used structlog.get_level_from_name, which does not exist.
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
