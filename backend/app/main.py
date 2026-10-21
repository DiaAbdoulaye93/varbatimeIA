"""FastAPI application: REST API under /api, health check at /health."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api.analyses import router as analyses_router
from app.config import get_settings
from app.db import get_engine, init_db
from app.pipeline.llm_client import AnthropicLlmClient
from app.schemas import HealthOut
from app.services.analysis_service import LlmClientFactory, fail_interrupted

APP_VERSION = version("sat-verbatim-analyzer")


def create_app(
    engine: Engine | None = None, llm_client_factory: LlmClientFactory | None = None
) -> FastAPI:
    """Build the app; tests pass their own engine and a fake LLM client factory."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(app.state.engine)
        fail_interrupted(app.state.engine)
        yield

    app = FastAPI(title="SAT verbatim analyzer", version=APP_VERSION, lifespan=lifespan)
    app.state.engine = engine or get_engine()
    app.state.llm_client_factory = llm_client_factory or AnthropicLlmClient
    app.include_router(analyses_router)

    @app.get("/health", response_model=HealthOut, tags=["health"])
    def health() -> HealthOut:
        return HealthOut(version=APP_VERSION)

    return app


app = create_app()
