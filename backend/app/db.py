"""Database engine (PostgreSQL via psycopg 3)."""

from functools import lru_cache

from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401 - registers the tables on SQLModel.metadata
from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        # Hosted databases put idle connections to sleep: test them before use.
        pool_pre_ping=True,
        # No server-side prepared statements, so a PgBouncer pool (Neon "pooled" URL) works.
        connect_args={"prepare_threshold": None},
    )


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
