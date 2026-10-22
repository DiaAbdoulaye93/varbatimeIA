"""FastAPI application: REST API under /api, health check at /health."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api.analyses import router as analyses_router
from app.auth import add_basic_auth
from app.config import get_settings
from app.db import get_engine, init_db
from app.pipeline.llm_client import AnthropicLlmClient
from app.schemas import HealthOut
from app.services.analysis_service import LlmClientFactory, fail_interrupted
from app.spa import INDEX, mount_spa

APP_VERSION = version("sat-verbatim-analyzer")


def create_app(
    engine: Engine | None = None,
    llm_client_factory: LlmClientFactory | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build the app; tests pass their own engine, a fake LLM client and a static folder."""
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
    if settings.app_password is not None:
        add_basic_auth(app, settings.app_username, settings.app_password.get_secret_value())

    @app.get("/health", response_model=HealthOut, tags=["health"])
    def health() -> HealthOut:
        return HealthOut(version=APP_VERSION)

    # Registered last: its catch-all route must not shadow the API routes.
    spa_dir = static_dir or settings.static_dir
    if (spa_dir / INDEX).is_file():
        mount_spa(app, spa_dir)
    return app


app = create_app()
