"""Shared fixtures: a PostgreSQL test database (TEST_DATABASE_URL), reset for every test."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlmodel import SQLModel, create_engine

from app import models  # noqa: F401 - registers the tables
from app.config import get_settings


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = create_engine(get_settings().test_database_url, pool_pre_ping=True)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Engine]:
    yield engine
    tables = ", ".join(t.name for t in SQLModel.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
