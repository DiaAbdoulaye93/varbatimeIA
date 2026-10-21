"""The built Angular app is served by FastAPI, with index.html as client-side fallback."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.main import create_app
from tests.test_api import FakeFactory


@pytest.fixture
def client(db: Engine, tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<app-root></app-root>", encoding="utf-8")
    (tmp_path / "chunk-ABC.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("nope", encoding="utf-8")
    return TestClient(create_app(engine=db, llm_client_factory=FakeFactory(), static_dir=tmp_path))


def test_serves_files_with_cache_headers(client: TestClient) -> None:
    asset = client.get("/chunk-ABC.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    index = client.get("/")
    assert "<app-root>" in index.text and index.headers["cache-control"] == "no-cache"


def test_client_routes_fall_back_to_index(client: TestClient) -> None:
    assert "<app-root>" in client.get("/analyses/123").text


def test_api_paths_are_not_shadowed(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/analyses").json() == []
    assert client.get("/api/unknown").status_code == 404


def test_no_path_traversal(client: TestClient) -> None:
    assert "nope" not in client.get("/../secret.txt").text
    assert "nope" not in client.get("/%2e%2e/secret.txt").text
