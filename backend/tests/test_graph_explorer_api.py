"""API tests for the member-facing Enterprise Graph explorer endpoints."""

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
            user_id="graph-user",
            organization_id="org-graph",
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


def test_search_entities_applies_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        search_entities=AsyncMock(
            return_value={
                "items": [
                    {
                        "entity_id": "entity-1",
                        "entity_type": "Vendor",
                        "canonical_name": "Acme Corp",
                        "normalized_name": "acme corp",
                        "aliases": ["Acme"],
                        "alias_count": 1,
                        "workspace_id": "ws-1",
                        "external_source_id": "src-1",
                        "resolution_status": "verified",
                        "resolution_confidence": 0.92,
                        "confidence": 0.95,
                        "last_updated_at": "2026-06-14T10:00:00Z",
                        "evidence_count": 2,
                        "related_document_count": 1,
                    }
                ],
                "total": 1,
                "skip": 10,
                "limit": 5,
                "query": "acme",
                "entity_type": "Vendor",
                "min_confidence": 0.8,
                "source_document_id": "doc-1",
                "source_connector": "confluence",
                "rel_type": "OWNS",
                "relationship_direction": "out",
            }
        ),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get(
        "/api/v1/graph/entities",
        params={
            "query": "acme",
            "entity_type": "Vendor",
            "min_confidence": 0.8,
            "source_document_id": "doc-1",
            "source_connector": "confluence",
            "rel_type": "OWNS",
            "relationship_direction": "out",
            "skip": 10,
            "limit": 5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_name"] == "Acme Corp"
    fake_service.search_entities.assert_awaited_once_with(
        organization_id="org-graph",
        query="acme",
        entity_type="Vendor",
        min_confidence=0.8,
        source_document_id="doc-1",
        source_connector="confluence",
        rel_type="OWNS",
        relationship_direction="out",
        skip=10,
        limit=5,
    )


def test_entity_detail_returns_provenance_and_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_entity_detail=AsyncMock(
            return_value={
                "entity": {
                    "entity_id": "entity-1",
                    "entity_type": "Vendor",
                    "canonical_name": "Acme Corp",
                    "normalized_name": "acme corp",
                    "aliases": ["Acme"],
                    "alias_count": 1,
                    "workspace_id": "ws-1",
                    "external_source_id": "src-1",
                    "resolution_status": "verified",
                    "resolution_confidence": 0.92,
                    "confidence": 0.95,
                    "last_updated_at": "2026-06-14T10:00:00Z",
                    "evidence_count": 2,
                    "related_document_count": 1,
                },
                "aliases": [
                    {
                        "alias_id": "alias-1",
                        "entity_id": "entity-1",
                        "alias_name": "Acme",
                        "normalized_name": "acme",
                        "source_document_id": "doc-1",
                        "chunk_id": "chunk-1",
                        "workspace_id": "ws-1",
                        "source_external_id": None,
                        "source_connector": "confluence",
                        "language": "en",
                        "confidence": 0.9,
                        "evidence_text": "Acme",
                        "page_number": 1,
                        "created_at": "2026-06-14T09:58:00Z",
                        "updated_at": "2026-06-14T09:58:00Z",
                    }
                ],
                "evidence": [
                    {
                        "chunk_id": "chunk-1",
                        "source_document_id": "doc-1",
                        "workspace_id": "ws-1",
                        "document_version_id": "v1",
                        "page_number": 1,
                        "source_connector": "confluence",
                        "external_url": "https://example.com/doc-1",
                        "extraction_run_id": "run-1",
                        "confidence": 0.9,
                        "evidence_text": "Acme Corp is our vendor.",
                        "citation_text": "Acme Corp is our vendor.",
                        "citation_reference": "Policy p. 1",
                        "created_at": "2026-06-14T09:58:00Z",
                    }
                ],
                "relationships": [
                    {
                        "relation_id": "rel-1",
                        "from_entity_id": "entity-1",
                        "rel_type": "OWNS",
                        "to_entity_id": "entity-2",
                        "status": "verified",
                        "confidence": 0.88,
                        "properties": {"weight": 1},
                    }
                ],
                "connected_documents": [
                    {
                        "document_id": "doc-1",
                        "page_numbers": [1],
                        "evidence_count": 1,
                        "max_confidence": 0.9,
                        "source_connectors": ["confluence"],
                    }
                ],
                "connected_entities": [
                    {
                        "entity_id": "entity-2",
                        "entity_type": "Organization",
                        "canonical_name": "Contoso",
                        "normalized_name": "contoso",
                        "relation_count": 1,
                    }
                ],
                "summary": {
                    "alias_count": 1,
                    "evidence_count": 1,
                    "relationship_count": 1,
                    "connected_document_count": 1,
                    "connected_entity_count": 1,
                },
            }
        ),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("member")

    client = TestClient(app)
    response = client.get("/api/v1/graph/entities/entity-1")

    assert response.status_code == 200
    body = response.json()
    assert body["entity"]["canonical_name"] == "Acme Corp"
    assert body["summary"]["connected_entity_count"] == 1
    assert body["connected_documents"][0]["document_id"] == "doc-1"
    fake_service.get_entity_detail.assert_awaited_once_with(
        organization_id="org-graph",
        entity_id="entity-1",
        rel_type=None,
        relationship_direction="both",
        limit=50,
    )


def test_graph_disabled_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/entities")

    assert response.status_code == 503
    assert response.json()["detail"] == "enterprise_graph_unavailable"
