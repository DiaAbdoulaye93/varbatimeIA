"""Hosting-related settings: database URL formats and the optional password."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.auth import add_basic_auth
from app.config import Settings
from app.main import create_app
from tests.test_api import FakeFactory


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pw@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        "postgres://user:pw@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        "postgresql+psycopg://user:pw@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require",
    ],
)
def test_hosted_database_urls_use_psycopg(url: str) -> None:
    settings = Settings(database_url=url)
    assert settings.database_url.startswith("postgresql+psycopg://user:pw@ep-x.")
    assert settings.database_url.endswith("?sslmode=require")


@pytest.fixture
def protected(db: Engine) -> TestClient:
    app = create_app(engine=db, llm_client_factory=FakeFactory())
    add_basic_auth(app, "sat", "s3cret")
    return TestClient(app)


def test_password_protects_api_and_dashboard(protected: TestClient) -> None:
    for path in ("/api/analyses", "/", "/analyses/123"):
        response = protected.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic")
    assert protected.get("/api/analyses", auth=("sat", "wrong")).status_code == 401
    assert protected.get("/api/analyses", auth=("sat", "s3cret")).status_code == 200


def test_health_stays_open_for_the_platform(protected: TestClient) -> None:
    assert protected.get("/health").json()["status"] == "ok"
