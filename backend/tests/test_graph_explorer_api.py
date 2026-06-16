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


# ------------------------------------------------------------------
# F269 — GET /graph/stats
# ------------------------------------------------------------------


def test_graph_stats_returns_overview(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_graph_stats=AsyncMock(
            return_value={
                "total_entities": 120,
                "total_relations": 54,
                "avg_confidence": 0.87,
                "low_confidence_count": 3,
                "entities_by_type": [
                    {
                        "entity_type": "Vendor",
                        "count": 80,
                        "avg_confidence": 0.91,
                    },
                    {
                        "entity_type": "Person",
                        "count": 40,
                        "avg_confidence": 0.82,
                    },
                ],
                "graph_available": True,
            }
        ),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["total_entities"] == 120
    assert body["total_relations"] == 54
    assert body["graph_available"] is True
    assert len(body["entities_by_type"]) == 2
    assert body["entities_by_type"][0]["entity_type"] == "Vendor"
    fake_service.get_graph_stats.assert_awaited_once_with(
        organization_id="org-graph"
    )


def test_graph_stats_returns_safe_zero_when_neo4j_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_graph_stats=AsyncMock(
            return_value={
                "total_entities": 0,
                "total_relations": 0,
                "avg_confidence": None,
                "low_confidence_count": 0,
                "entities_by_type": [],
                "graph_available": False,
            }
        ),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["total_entities"] == 0
    assert body["graph_available"] is False
    assert body["entities_by_type"] == []


def test_graph_stats_cross_tenant_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    captured: list[str] = []

    async def _stats(*, organization_id: str) -> dict:
        captured.append(str(organization_id))
        return {
            "total_entities": 0,
            "total_relations": 0,
            "avg_confidence": None,
            "low_confidence_count": 0,
            "entities_by_type": [],
            "graph_available": True,
        }

    fake_service = SimpleNamespace(is_available=lambda: True, get_graph_stats=_stats)
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/stats")

    assert response.status_code == 200
    # The org comes from the authenticated principal, not from query params
    assert captured == ["org-graph"]


# ------------------------------------------------------------------
# F269 — GET /graph/relationships
# ------------------------------------------------------------------


def test_list_relationships_returns_paginated_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        list_user_relationships=AsyncMock(
            return_value={
                "items": [
                    {
                        "relation_id": "rel-1",
                        "from_entity_id": "entity-1",
                        "rel_type": "OWNS",
                        "to_entity_id": "entity-2",
                        "status": "verified",
                        "confidence": 0.9,
                        "properties": {},
                    }
                ],
                "total": 1,
                "skip": 0,
                "limit": 25,
                "has_more": False,
            }
        ),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/relationships")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["rel_type"] == "OWNS"
    assert body["has_more"] is False
    fake_service.list_user_relationships.assert_awaited_once_with(
        organization_id="org-graph",
        rel_type=None,
        min_confidence=None,
        skip=0,
        limit=25,
    )


def test_list_relationships_filters_are_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        list_user_relationships=AsyncMock(
            return_value={
                "items": [],
                "total": 0,
                "skip": 0,
                "limit": 10,
                "has_more": False,
            }
        ),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get(
        "/api/v1/graph/relationships",
        params={"rel_type": "OWNED_BY", "min_confidence": 0.85, "limit": 10},
    )

    assert response.status_code == 200
    fake_service.list_user_relationships.assert_awaited_once_with(
        organization_id="org-graph",
        rel_type="OWNED_BY",
        min_confidence=0.85,
        skip=0,
        limit=10,
    )


def test_list_relationships_503_when_graph_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(is_available=lambda: False)
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/relationships")

    assert response.status_code == 503


def test_list_relationships_cross_tenant_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    captured: list[str] = []

    async def _list_rels(*, organization_id: str, **_kwargs: Any) -> dict:
        captured.append(str(organization_id))
        return {
            "items": [],
            "total": 0,
            "skip": 0,
            "limit": 25,
            "has_more": False,
        }

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        list_user_relationships=_list_rels,
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/relationships")

    assert response.status_code == 200
    # Organization ID comes from the authenticated principal, not from query params
    assert captured == ["org-graph"]


# ------------------------------------------------------------------
# F269 — GET /graph/entities/{id}/neighbors
# ------------------------------------------------------------------


def test_entity_neighbors_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_entity_neighbors=AsyncMock(
            return_value=[
                {
                    "entity_id": "entity-2",
                    "entity_type": "Vendor",
                    "canonical_name": "Partner Ltd",
                    "normalized_name": "partner ltd",
                    "relation_count": 3,
                    "confidence": 0.88,
                    "rel_type": "OWNS",
                    "direction": "out",
                }
            ]
        ),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get(
        "/api/v1/graph/entities/entity-1/neighbors",
        params={"depth": 2, "limit": 20},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["canonical_name"] == "Partner Ltd"
    assert body[0]["rel_type"] == "OWNS"
    fake_service.get_entity_neighbors.assert_awaited_once_with(
        organization_id="org-graph",
        entity_id="entity-1",
        depth=2,
        limit=20,
        relationship_types=None,
    )


def test_entity_neighbors_rel_type_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_entity_neighbors=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get(
        "/api/v1/graph/entities/entity-1/neighbors",
        params={"rel_type": "OWNS"},
    )

    assert response.status_code == 200
    fake_service.get_entity_neighbors.assert_awaited_once_with(
        organization_id="org-graph",
        entity_id="entity-1",
        depth=2,
        limit=20,
        relationship_types=["OWNS"],
    )


def test_entity_neighbors_depth_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_entity_neighbors=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get(
        "/api/v1/graph/entities/entity-1/neighbors",
        params={"depth": 10},  # exceeds max of 5
    )

    assert response.status_code == 422


def test_entity_neighbors_503_when_graph_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    fake_service = SimpleNamespace(is_available=lambda: False)
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/entities/entity-1/neighbors")

    assert response.status_code == 503


def test_entity_neighbors_cross_tenant_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    captured: list[str] = []

    async def _neighbors(*, organization_id: str, **_kwargs: Any) -> list[dict]:
        captured.append(str(organization_id))
        return []

    fake_service = SimpleNamespace(
        is_available=lambda: True,
        get_entity_neighbors=_neighbors,
    )
    monkeypatch.setattr(graph_http, "_graph_service", lambda: fake_service)
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")

    client = TestClient(app)
    response = client.get("/api/v1/graph/entities/entity-x/neighbors")

    assert response.status_code == 200
    # Organization ID comes from the authenticated principal, not from path params
    assert captured == ["org-graph"]
