from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import get_settings
from app.db import init_db
from app.logging import setup_logging, get_logger
from app.rate_limit import rate_limit_middleware
from app.api import router
from app.version import APP_VERSION, MODEL_VERSION


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = get_logger("startup")
    logger.info(
        "starting",
        app_version=APP_VERSION,
        model_version=MODEL_VERSION,
    )
    init_db()
    logger.info("database_initialized")
    yield
    logger.info("shutdown")


app = FastAPI(
    title="Hedge Fund V7",
    description=(
        "Multi-agent trading engine with execution, live portfolio state, "
        "rebalancing, fund-level risk guards, and optional TradingAgents "
        "(LLM) signal provider."
    ),
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(rate_limit_middleware)

app.include_router(router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
