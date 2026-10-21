"""REST API on the PostgreSQL test database, pipeline running on FakeLlmClient."""

import csv
import io
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session

from app.config import Settings
from app.main import create_app
from app.models import STATUS_PROCESSING, Analysis
from app.pipeline.llm_client import LlmError
from app.services.analysis_service import INTERRUPTED_ERROR, content_hash
from tests.fakes import FakeLlmClient, load_fixture, load_text_fixture
from tests.test_pipeline_mocked import CONTEXT, TEXTS, extraction_payload


def csv_bytes(texts: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "verbatim"])
    writer.writerows([i, t] for i, t in enumerate(texts, start=1))
    return buffer.getvalue().encode("utf-8")


class FakeFactory:
    """LLM client factory handing out FakeLlmClient instances and keeping them."""

    def __init__(self, cluster_payload: Any = None) -> None:
        self.cluster_payload = cluster_payload or load_fixture("cluster_mapping.json")
        self.clients: list[FakeLlmClient] = []

    def __call__(self, settings: Settings) -> FakeLlmClient:
        client = FakeLlmClient(
            tool_payloads={
                "record_extraction": [extraction_payload],
                "record_theme_mapping": [self.cluster_payload],
            },
            texts=[load_text_fixture("synthesis.md")],
        )
        self.clients.append(client)
        return client


@pytest.fixture
def factory() -> FakeFactory:
    return FakeFactory()


@pytest.fixture
def api(db: Engine, factory: FakeFactory) -> Iterator[TestClient]:
    with TestClient(create_app(engine=db, llm_client_factory=factory)) as client:
        yield client


def post(api: TestClient, texts: list[str] = TEXTS, context: str = CONTEXT) -> dict[str, Any]:
    response = api.post(
        "/api/analyses",
        files={"file": ("enquete_test.csv", csv_bytes(texts), "text/csv")},
        data={"context": context},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_health(api: TestClient) -> None:
    body = api.get("/health").json()
    assert body["status"] == "ok" and body["version"]


def test_create_runs_the_pipeline_in_background(api: TestClient) -> None:
    created = post(api)
    assert created["cached"] is False
    # TestClient runs background tasks before returning the response.
    detail = api.get(f"/api/analyses/{created['id']}").json()
    assert detail["status"] == "done", detail
    assert (detail["progress"], detail["current_step"]) == (100, "done")
    assert detail["name"] == "enquete_test"
    assert detail["total_verbatims"] == 8
    assert detail["stats"]["n_used"] == 6 and detail["stats"]["n_skipped"] == 2
    assert detail["synthesis_md"].startswith("## Chiffres clés")

    listed = api.get("/api/analyses").json()
    assert [a["id"] for a in listed] == [created["id"]]


def test_identical_upload_reuses_the_analysis(api: TestClient, factory: FakeFactory) -> None:
    first = post(api)
    second = post(api)
    assert second == {"id": first["id"], "status": "done", "cached": True}
    assert len(factory.clients) == 1, "no LLM call for a cached analysis"
    assert post(api, context="Autre contexte")["id"] != first["id"]


def test_themes_endpoint(api: TestClient) -> None:
    analysis_id = post(api)["id"]
    themes = api.get(f"/api/analyses/{analysis_id}/themes").json()
    assert [t["rank"] for t in themes] == list(range(1, len(themes) + 1))
    reseau = themes[0]
    assert reseau["label"] == "Couverture réseau"
    assert (reseau["count"], reseau["pct"]) == (2, 33)
    assert reseau["representatives"][0] == {"idx": 1, "text": TEXTS[0]}
    assert themes[-1]["label"] == "Autres remarques"


def test_verbatims_endpoint_filters_and_pages(api: TestClient) -> None:
    analysis_id = post(api)["id"]
    url = f"/api/analyses/{analysis_id}/verbatims"

    page = api.get(url, params={"size": 4}).json()
    assert (page["total"], len(page["items"]), page["page"]) == (6, 4, 1)
    assert [v["idx"] for v in page["items"]] == [1, 3, 4, 6]

    assert api.get(url, params={"include_skipped": True}).json()["total"] == 8
    negatives = api.get(url, params={"sentiment": "negative"}).json()["items"]
    assert {v["idx"] for v in negatives} == {1, 3, 7}
    assert [v["idx"] for v in api.get(url, params={"q": "1234"}).json()["items"]] == [3]

    reseau_id = api.get(f"/api/analyses/{analysis_id}/themes").json()[0]["id"]
    in_theme = api.get(url, params={"theme_id": reseau_id}).json()["items"]
    assert [v["idx"] for v in in_theme] == [1, 6]
    assert reseau_id in in_theme[1]["theme_ids"]

    assert api.get(url, params={"sentiment": "angry"}).status_code == 422


def test_usage_endpoint(api: TestClient) -> None:
    usage = api.get(f"/api/analyses/{post(api)['id']}/usage").json()
    assert [s["step"] for s in usage["steps"]] == ["extract", "cluster", "synthesize"]
    assert usage["total"]["calls"] == 3
    assert usage["total"]["input_tokens"] == 300
    assert usage["total"]["cost_usd"] is not None


def test_failed_analysis_keeps_its_error_and_usage(db: Engine) -> None:
    def broken_cluster(user: str) -> dict[str, Any]:
        raise LlmError("cluster: model refused the request (category=None)")

    factory = FakeFactory(cluster_payload=broken_cluster)
    with TestClient(create_app(engine=db, llm_client_factory=factory)) as api:
        analysis_id = post(api)["id"]
        detail = api.get(f"/api/analyses/{analysis_id}").json()
        assert detail["status"] == "failed"
        assert "refused" in detail["error"]
        assert api.get(f"/api/analyses/{analysis_id}/usage").json()["total"]["calls"] == 2
        # A failed analysis is not reused: a new upload runs again.
        assert post(api)["cached"] is False


def test_invalid_csv_and_unknown_ids(api: TestClient) -> None:
    response = api.post(
        "/api/analyses", files={"file": ("x.csv", b"id,texte\n1,abc\n", "text/csv")}
    )
    assert response.status_code == 422
    assert "verbatim" in response.json()["detail"]
    for suffix in ("", "/themes", "/verbatims", "/usage"):
        assert api.get(f"/api/analyses/unknown{suffix}").status_code == 404


def test_startup_fails_analyses_left_running(db: Engine, factory: FakeFactory) -> None:
    with Session(db) as session:
        session.add(
            Analysis(
                name="stale",
                context="",
                status=STATUS_PROCESSING,
                content_hash=content_hash(["x"], ""),
            )
        )
        session.commit()
    with TestClient(create_app(engine=db, llm_client_factory=factory)) as api:
        stale = api.get("/api/analyses").json()[0]
        assert stale["status"] == "failed"
        assert api.get(f"/api/analyses/{stale['id']}").json()["error"] == INTERRUPTED_ERROR
