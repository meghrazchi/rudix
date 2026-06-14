"""API tests for GET /graph/documents/{document_id}/insights (F289)."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

import app.interfaces.http.graph_explorer as graph_http
from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.main import app


def _principal_override(role: str = "viewer"):
    async def _dep() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id="insights-user",
            organization_id="org-insights",
            roles=[role],
            auth_provider="app",
        )

    return _dep


@pytest.fixture(autouse=True)
def _reset_overrides() -> Any:
    previous = dict(app.dependency_overrides)
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def _make_insights_data(**overrides: Any) -> dict:
    base: dict = {
        "entity_count": 5,
        "relation_count": 3,
        "avg_confidence": 0.87,
        "entities_by_type": {"Person": 3, "Organization": 2},
        "top_entities": [
            {
                "entity_id": "e-1",
                "entity_type": "Person",
                "canonical_name": "Alice",
                "confidence": 0.9,
                "evidence_count": 2,
            },
            {
                "entity_id": "e-2",
                "entity_type": "Organization",
                "canonical_name": "Acme Corp",
                "confidence": 0.85,
                "evidence_count": 3,
            },
        ],
        "recent_evidence": [
            {
                "chunk_id": "chunk-1",
                "source_document_id": "doc-abc",
                "page_number": 4,
                "confidence": 0.9,
                "evidence_text": "Alice works at Acme Corp.",
                "citation_text": None,
                "citation_reference": "Report 2026, p. 4",
                "extraction_run_id": "run-1",
            }
        ],
        "extraction_runs": [
            {
                "run_id": "run-1",
                "status": "completed",
                "strategy": "llm_extraction",
                "entity_count": 5,
                "error": None,
                "created_at": "2026-06-14T10:00:00Z",
                "updated_at": "2026-06-14T10:01:30Z",
            }
        ],
        "last_run_at": "2026-06-14T10:01:30Z",
    }
    base.update(overrides)
    return base


def test_insights_returns_entity_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_document_insights=AsyncMock(return_value=_make_insights_data()),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/doc-abc/insights")

    assert response.status_code == 200
    body = response.json()
    assert body["entity_count"] == 5
    assert body["relation_count"] == 3
    assert body["avg_confidence"] == pytest.approx(0.87)
    assert body["entities_by_type"] == {"Person": 3, "Organization": 2}
    assert body["last_run_at"] == "2026-06-14T10:01:30Z"

    fake_service.get_document_insights.assert_awaited_once_with(
        organization_id="org-insights",
        document_id="doc-abc",
    )


def test_insights_returns_top_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_document_insights=AsyncMock(return_value=_make_insights_data()),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/doc-abc/insights")

    assert response.status_code == 200
    body = response.json()
    entities = body["top_entities"]
    assert len(entities) == 2
    assert entities[0]["entity_id"] == "e-1"
    assert entities[0]["canonical_name"] == "Alice"
    assert entities[0]["entity_type"] == "Person"
    assert entities[0]["confidence"] == pytest.approx(0.9)


def test_insights_returns_evidence_snippets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_document_insights=AsyncMock(return_value=_make_insights_data()),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/doc-abc/insights")

    assert response.status_code == 200
    body = response.json()
    evidence = body["recent_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["chunk_id"] == "chunk-1"
    assert evidence[0]["page_number"] == 4
    assert evidence[0]["evidence_text"] == "Alice works at Acme Corp."
    assert evidence[0]["citation_reference"] == "Report 2026, p. 4"


def test_insights_returns_extraction_run_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_document_insights=AsyncMock(return_value=_make_insights_data()),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/doc-abc/insights")

    assert response.status_code == 200
    body = response.json()
    runs = body["extraction_runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run-1"
    assert runs[0]["status"] == "completed"
    assert runs[0]["entity_count"] == 5
    assert runs[0]["strategy"] == "llm_extraction"


def test_insights_when_graph_unavailable_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(is_available=lambda: False)
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/doc-abc/insights")

    assert response.status_code == 503
    assert "enterprise_graph_unavailable" in response.json()["detail"]


def test_insights_empty_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    empty_data = _make_insights_data(
        entity_count=0,
        relation_count=0,
        avg_confidence=None,
        entities_by_type={},
        top_entities=[],
        recent_evidence=[],
        extraction_runs=[],
        last_run_at=None,
    )
    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_document_insights=AsyncMock(return_value=empty_data),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/doc-abc/insights")

    assert response.status_code == 200
    body = response.json()
    assert body["entity_count"] == 0
    assert body["relation_count"] == 0
    assert body["avg_confidence"] is None
    assert body["entities_by_type"] == {}
    assert body["top_entities"] == []
    assert body["recent_evidence"] == []
    assert body["extraction_runs"] == []
    assert body["last_run_at"] is None


def test_insights_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/doc-abc/insights")
    assert response.status_code in {401, 403}


def test_insights_failed_extraction_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    data = _make_insights_data(
        entity_count=0,
        relation_count=0,
        extraction_runs=[
            {
                "run_id": "run-fail",
                "status": "failed",
                "strategy": "llm_extraction",
                "entity_count": None,
                "error": "LLM timeout after 30s",
                "created_at": "2026-06-14T09:00:00Z",
                "updated_at": "2026-06-14T09:00:30Z",
            }
        ],
        last_run_at="2026-06-14T09:00:30Z",
    )
    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_document_insights=AsyncMock(return_value=data),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/doc-abc/insights")

    assert response.status_code == 200
    body = response.json()
    run = body["extraction_runs"][0]
    assert run["status"] == "failed"
    assert run["error"] == "LLM timeout after 30s"
    assert run["entity_count"] is None


def test_insights_document_id_is_org_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Organization ID from the token — not user input — scopes the query."""
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_document_insights=AsyncMock(return_value=_make_insights_data()),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("admin")

    client = TestClient(app)
    response = client.get("/api/v1/graph/documents/my-doc/insights")

    assert response.status_code == 200
    fake_service.get_document_insights.assert_awaited_once_with(
        organization_id="org-insights",
        document_id="my-doc",
    )
