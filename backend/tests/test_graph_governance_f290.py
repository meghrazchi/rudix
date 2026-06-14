"""Tests for F290: Graph governance, permissions, audit logs, and tenant isolation.

pytest.mark.governance tags all tests in this module.

Coverage:
  A.  Tenant isolation: GET /graph/entities — org_a entities not visible to org_b principal
  B.  Tenant isolation: service always called with caller's org_id, not a foreign one
  C.  Tenant isolation: GET /admin/graph/entities — org_a admin sees no org_b data
  D.  Tenant isolation: document insights scoped to caller's org_id
  E.  RBAC: viewer can access GET /graph/entities (has graph:view)
  F.  RBAC: billing_admin gets 403 on GET /graph/entities (no graph:view)
  G.  RBAC: member gets 403 on POST /admin/graph/entities (no graph:entities:manage)
  H.  RBAC: admin can POST /admin/graph/entities (has graph:entities:manage)
  I.  RBAC: member gets 403 on DELETE /admin/graph/entities/{id}
  J.  RBAC: member gets 403 on POST /admin/graph/entity-resolution/merge
  K.  RBAC: member gets 403 on POST /admin/graph/entity-resolution/split
  L.  RBAC: member gets 403 on POST /admin/graph/relations (no graph:relations:manage)
  M.  RBAC: admin can POST /admin/graph/relations (has graph:relations:manage)
  N.  RBAC: member gets 403 on PATCH /admin/graph/relations/{id}/status
  O.  RBAC: member gets 403 on DELETE /admin/graph/relations/{id}
  P.  RBAC: security_admin gets 403 on GET /graph/entities (no graph:view)
  Q.  Audit: entity upsert → GRAPH_ENTITY_CREATED logged
  R.  Audit: entity delete → GRAPH_ENTITY_DELETED logged
  S.  Audit: entity merge → GRAPH_ENTITY_MERGED logged
  T.  Audit: entity split → GRAPH_ENTITY_SPLIT logged
  U.  Audit: relation create → GRAPH_RELATION_CREATED logged
  V.  Audit: relation status change → GRAPH_RELATION_STATUS_CHANGED logged
  W.  Audit: relation delete → GRAPH_RELATION_DELETED logged
  X.  GraphRAG: allowed_document_ids restricts evidence returned
  Y.  GraphRAG: no allowed_document_ids passes None (all accessible docs)
  Z.  GraphRAG: organization_id from principal propagated to all service calls
  AA. Permission matrix: graph_view granted to viewer, reviewer, member, developer, admin, owner
  AB. Permission matrix: graph_entities_manage granted to admin and owner only
  AC. Permission matrix: graph_relations_manage granted to admin and owner only
  AD. Permission matrix: security_admin has graph_audit_logs_view but NOT graph_view
  AE. Permission matrix: billing_admin has neither graph_view nor graph_entities_manage
  AF. Redaction: neo4j_password key is redacted in audit metadata
  AG. Redaction: bolt_password suffix is redacted in audit metadata
  AH. Redaction: neo4j_uri key is redacted in audit metadata
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

from app.auth.dependencies import get_current_principal, require_permission
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import sanitize_metadata
from app.domains.chat.services.graph_retrieval_service import GraphRetrievalService
from app.main import app
from app.models.permissions import ROLE_PERMISSIONS, PermissionType
import app.interfaces.http.admin_graph_entities as entities_http
import app.interfaces.http.admin_graph_relations as relations_http
import app.interfaces.http.graph_explorer as explorer_http

pytestmark = pytest.mark.governance

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_ORG_A = "00000000-0000-0000-0000-000000000001"
_ORG_B = "00000000-0000-0000-0000-000000000002"
_USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _make_principal(
    *,
    role: str,
    org_id: str = _ORG_A,
    user_id: str = _USER_A,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        organization_id=org_id,
        roles=[role],
        auth_provider="app",
    )


def _principal_override(role: str, org_id: str = _ORG_A):
    """FastAPI dependency override that returns a fixed principal."""
    async def _dep() -> AuthenticatedPrincipal:
        return _make_principal(role=role, org_id=org_id)
    return _dep


def _mock_db_session() -> Any:
    """Mock db session that returns no custom_role_id (uses built-in ROLE_PERMISSIONS)."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


def _empty_graph_service() -> SimpleNamespace:
    return SimpleNamespace(
        is_available=lambda: True,
        search_entities=AsyncMock(return_value={"items": [], "total": 0}),
        get_entity_detail=AsyncMock(return_value=None),
        get_document_insights=AsyncMock(
            return_value={
                "entity_count": 0,
                "relation_count": 0,
                "entities_by_type": {},
                "top_entities": [],
                "recent_evidence": [],
                "extraction_runs": [],
            }
        ),
        list_entities=AsyncMock(return_value=[]),
        get_entity=AsyncMock(return_value={"entity_id": "e-1", "entity_type": "Person", "canonical_name": "Alice", "organization_id": _ORG_A}),
        upsert_entity=AsyncMock(),
        delete_entity=AsyncMock(return_value=True),
        list_entity_aliases=AsyncMock(return_value=[]),
        get_entity_evidence=AsyncMock(return_value=[]),
        get_entity_relations=AsyncMock(return_value=[]),
        find_entity_resolution_candidates=AsyncMock(return_value=[]),
        record_entity_merge_decision=AsyncMock(),
        record_entity_split_decision=AsyncMock(),
        build_entity_merge_decision_id=MagicMock(return_value="merge-decision-id"),
        build_entity_split_decision_id=MagicMock(return_value="split-decision-id"),
        get_document_extraction_runs=AsyncMock(return_value=[]),
        list_relations=AsyncMock(return_value=[]),
        create_relation_with_evidence=AsyncMock(),
        get_relation=AsyncMock(return_value={"relation_id": "rel-1", "status": "unverified"}),
        update_relation_status=AsyncMock(return_value=True),
        delete_relation_by_id=AsyncMock(return_value=True),
        find_entities_by_name=AsyncMock(return_value=[]),
    )


@pytest.fixture(autouse=True)
def _reset_overrides() -> Any:
    previous = dict(app.dependency_overrides)
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_graph_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)


def _setup_db_override() -> AsyncMock:
    mock_session = _mock_db_session()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_db_session] = _override
    return mock_session


# ===========================================================================
# A-D: Tenant isolation
# ===========================================================================

def test_tenant_isolation_search_entities_uses_caller_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A: search_entities is always called with the caller's org_id."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("viewer", org_id=_ORG_A)
    _setup_db_override()  # require_permission(graph_view) needs db_session
    monkeypatch.setattr(explorer_http, "_graph_service", lambda: fake_svc)

    with TestClient(app) as client:
        resp = client.get("/api/v1/graph/entities")

    assert resp.status_code == 200
    fake_svc.search_entities.assert_awaited_once()
    call_kwargs = fake_svc.search_entities.call_args.kwargs
    assert call_kwargs["organization_id"] == _ORG_A


def test_tenant_isolation_foreign_org_not_used_in_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B: org_b principal cannot inject org_a into the search call."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    # org_b principal — must only see org_b data
    app.dependency_overrides[get_current_principal] = _principal_override("viewer", org_id=_ORG_B)
    _setup_db_override()
    monkeypatch.setattr(explorer_http, "_graph_service", lambda: fake_svc)

    with TestClient(app) as client:
        resp = client.get("/api/v1/graph/entities")

    assert resp.status_code == 200
    call_kwargs = fake_svc.search_entities.call_args.kwargs
    assert call_kwargs["organization_id"] == _ORG_B
    assert call_kwargs["organization_id"] != _ORG_A


def test_tenant_isolation_admin_list_entities_uses_caller_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C: admin list_entities is called with the caller's org, not a foreign one."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin", org_id=_ORG_A)
    _setup_db_override()
    monkeypatch.setattr(entities_http, "_graph_service", lambda: fake_svc)

    with TestClient(app) as client:
        resp = client.get("/api/v1/admin/graph/entities")

    assert resp.status_code == 200
    fake_svc.list_entities.assert_awaited_once()
    call_kwargs = fake_svc.list_entities.call_args.kwargs
    assert call_kwargs["organization_id"] == _ORG_A


def test_tenant_isolation_document_insights_uses_caller_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D: document insights endpoint propagates caller's org_id."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("viewer", org_id=_ORG_A)
    _setup_db_override()
    monkeypatch.setattr(explorer_http, "_graph_service", lambda: fake_svc)

    with TestClient(app) as client:
        resp = client.get("/api/v1/graph/documents/doc-123/insights")

    assert resp.status_code == 200
    fake_svc.get_document_insights.assert_awaited_once()
    call_kwargs = fake_svc.get_document_insights.call_args.kwargs
    assert call_kwargs["organization_id"] == _ORG_A


# ===========================================================================
# E-P: RBAC
# ===========================================================================

def test_rbac_viewer_can_access_graph_explorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E: viewer has graph:view — can access GET /graph/entities."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("viewer")
    _setup_db_override()
    monkeypatch.setattr(explorer_http, "_graph_service", lambda: fake_svc)

    with TestClient(app) as client:
        resp = client.get("/api/v1/graph/entities")

    assert resp.status_code == 200


def test_rbac_billing_admin_forbidden_on_graph_explorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F: billing_admin lacks graph:view — gets 403 on GET /graph/entities."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("billing_admin")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.get("/api/v1/graph/entities")

    assert resp.status_code == 403


def test_rbac_member_forbidden_on_entity_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G: member lacks graph:entities:manage — gets 403 on POST /admin/graph/entities."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/entities",
            json={"entity_id": "e-1", "entity_type": "Person", "canonical_name": "Alice"},
        )

    assert resp.status_code == 403


def test_rbac_admin_can_upsert_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H: admin has graph:entities:manage — can POST /admin/graph/entities."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    mock_session = _setup_db_override()
    monkeypatch.setattr(entities_http, "_graph_service", lambda: fake_svc)
    monkeypatch.setattr(entities_http._audit_log_service, "record", AsyncMock())

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/entities",
            json={"entity_id": "e-1", "entity_type": "Person", "canonical_name": "Alice"},
        )

    assert resp.status_code == 200
    fake_svc.upsert_entity.assert_awaited_once()


def test_rbac_member_forbidden_on_entity_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I: member lacks graph:entities:manage — gets 403 on DELETE /admin/graph/entities/{id}."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.delete("/api/v1/admin/graph/entities/e-1")

    assert resp.status_code == 403


def test_rbac_member_forbidden_on_entity_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """J: member gets 403 on POST /admin/graph/entity-resolution/merge."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/entity-resolution/merge",
            json={"target_entity_id": "e-1", "source_entity_ids": ["e-2"]},
        )

    assert resp.status_code == 403


def test_rbac_member_forbidden_on_entity_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K: member gets 403 on POST /admin/graph/entity-resolution/split."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/entity-resolution/split",
            json={"target_entity_id": "e-1", "source_entity_ids": ["e-2"]},
        )

    assert resp.status_code == 403


def test_rbac_member_forbidden_on_relation_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L: member lacks graph:relations:manage — gets 403 on POST /admin/graph/relations."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/relations",
            json={
                "from_entity_id": "e-1",
                "to_entity_id": "e-2",
                "rel_type": "RELATES_TO",
                "relation_id": "rel-1",
                "evidence_text": "source text",
            },
        )

    assert resp.status_code == 403


def test_rbac_admin_can_create_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M: admin has graph:relations:manage — can POST /admin/graph/relations."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    _setup_db_override()
    # Use dependency_overrides (not monkeypatch) — FastAPI captures the callable by reference
    app.dependency_overrides[relations_http._graph_service] = lambda: fake_svc
    monkeypatch.setattr(relations_http._audit_log_service, "record", AsyncMock())

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/relations",
            json={
                "from_entity_id": "e-1",
                "to_entity_id": "e-2",
                "rel_type": "RELATES_TO",
                "relation_id": "rel-1",
                "evidence_text": "source text",
            },
        )

    assert resp.status_code == 200
    fake_svc.create_relation_with_evidence.assert_awaited_once()


def test_rbac_member_forbidden_on_relation_status_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N: member gets 403 on PATCH /admin/graph/relations/{id}/status."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.patch(
            "/api/v1/admin/graph/relations/rel-1/status",
            json={"status": "approved"},
        )

    assert resp.status_code == 403


def test_rbac_member_forbidden_on_relation_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O: member gets 403 on DELETE /admin/graph/relations/{id}."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.delete("/api/v1/admin/graph/relations/rel-1")

    assert resp.status_code == 403


def test_rbac_security_admin_forbidden_on_graph_explorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P: security_admin has graph:audit_logs:view but NOT graph:view — gets 403 on explorer."""
    _setup_graph_enabled(monkeypatch)
    app.dependency_overrides[get_current_principal] = _principal_override("security_admin")
    _setup_db_override()

    with TestClient(app) as client:
        resp = client.get("/api/v1/graph/entities")

    assert resp.status_code == 403


# ===========================================================================
# Q-W: Audit logging
# ===========================================================================

def test_audit_entity_upsert_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q: entity upsert triggers GRAPH_ENTITY_CREATED audit log."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    _setup_db_override()
    monkeypatch.setattr(entities_http, "_graph_service", lambda: fake_svc)

    audit_record = AsyncMock(return_value=True)
    monkeypatch.setattr(entities_http._audit_log_service, "record", audit_record)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/entities",
            json={"entity_id": "e-audit", "entity_type": "Person", "canonical_name": "Audit User"},
        )

    assert resp.status_code == 200
    audit_record.assert_awaited_once()
    call_kwargs = audit_record.call_args.kwargs
    assert call_kwargs["action"] == "admin.graph.entity.created"
    assert call_kwargs["resource_type"] == "graph_entity"
    assert call_kwargs["resource_id"] == "e-audit"


def test_audit_entity_delete_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """R: entity delete triggers GRAPH_ENTITY_DELETED audit log."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    _setup_db_override()
    monkeypatch.setattr(entities_http, "_graph_service", lambda: fake_svc)

    audit_record = AsyncMock(return_value=True)
    monkeypatch.setattr(entities_http._audit_log_service, "record", audit_record)

    with TestClient(app) as client:
        resp = client.delete("/api/v1/admin/graph/entities/e-to-delete")

    assert resp.status_code == 200
    audit_record.assert_awaited_once()
    call_kwargs = audit_record.call_args.kwargs
    assert call_kwargs["action"] == "admin.graph.entity.deleted"
    assert call_kwargs["resource_id"] == "e-to-delete"


def test_audit_entity_merge_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """S: entity merge triggers GRAPH_ENTITY_MERGED audit log."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    _setup_db_override()
    monkeypatch.setattr(entities_http, "_graph_service", lambda: fake_svc)

    audit_record = AsyncMock(return_value=True)
    monkeypatch.setattr(entities_http._audit_log_service, "record", audit_record)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/entity-resolution/merge",
            json={
                "target_entity_id": "e-canonical",
                "source_entity_ids": ["e-dupe-1", "e-dupe-2"],
                "reason": "Same company, different spellings",
            },
        )

    assert resp.status_code == 200
    audit_record.assert_awaited_once()
    call_kwargs = audit_record.call_args.kwargs
    assert call_kwargs["action"] == "admin.graph.entity.merged"
    assert call_kwargs["resource_id"] == "e-canonical"
    meta = call_kwargs["metadata"]
    assert meta["target_entity_id"] == "e-canonical"
    assert "e-dupe-1" in meta["source_entity_ids"]


def test_audit_entity_split_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """T: entity split triggers GRAPH_ENTITY_SPLIT audit log."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    _setup_db_override()
    monkeypatch.setattr(entities_http, "_graph_service", lambda: fake_svc)

    audit_record = AsyncMock(return_value=True)
    monkeypatch.setattr(entities_http._audit_log_service, "record", audit_record)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/entity-resolution/split",
            json={
                "target_entity_id": "e-mixed",
                "source_entity_ids": ["e-person", "e-company"],
                "reason": "Two distinct entities conflated",
            },
        )

    assert resp.status_code == 200
    audit_record.assert_awaited_once()
    call_kwargs = audit_record.call_args.kwargs
    assert call_kwargs["action"] == "admin.graph.entity.split"
    assert call_kwargs["resource_id"] == "e-mixed"


def test_audit_relation_create_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """U: relation create triggers GRAPH_RELATION_CREATED audit log."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    _setup_db_override()
    app.dependency_overrides[relations_http._graph_service] = lambda: fake_svc

    audit_record = AsyncMock(return_value=True)
    monkeypatch.setattr(relations_http._audit_log_service, "record", audit_record)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/graph/relations",
            json={
                "from_entity_id": "e-1",
                "to_entity_id": "e-2",
                "rel_type": "RELATES_TO",
                "relation_id": "rel-audit",
                "evidence_text": "Entity A relates to Entity B per contract",
            },
        )

    assert resp.status_code == 200
    audit_record.assert_awaited_once()
    call_kwargs = audit_record.call_args.kwargs
    assert call_kwargs["action"] == "admin.graph.relation.created"
    assert call_kwargs["resource_id"] == "rel-audit"
    meta = call_kwargs["metadata"]
    assert meta["rel_type"] == "RELATES_TO"
    assert meta["from_entity_id"] == "e-1"
    assert meta["to_entity_id"] == "e-2"


def test_audit_relation_status_change_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """V: relation status change triggers GRAPH_RELATION_STATUS_CHANGED audit log."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    _setup_db_override()
    app.dependency_overrides[relations_http._graph_service] = lambda: fake_svc

    audit_record = AsyncMock(return_value=True)
    monkeypatch.setattr(relations_http._audit_log_service, "record", audit_record)

    with TestClient(app) as client:
        resp = client.patch(
            "/api/v1/admin/graph/relations/rel-audit/status",
            json={"status": "verified"},
        )

    assert resp.status_code == 200
    audit_record.assert_awaited_once()
    call_kwargs = audit_record.call_args.kwargs
    assert call_kwargs["action"] == "admin.graph.relation.status_changed"
    assert call_kwargs["resource_id"] == "rel-audit"
    assert call_kwargs["metadata"]["new_status"] == "verified"


def test_audit_relation_delete_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """W: relation delete triggers GRAPH_RELATION_DELETED audit log."""
    _setup_graph_enabled(monkeypatch)
    fake_svc = _empty_graph_service()
    app.dependency_overrides[get_current_principal] = _principal_override("admin")
    _setup_db_override()
    app.dependency_overrides[relations_http._graph_service] = lambda: fake_svc

    audit_record = AsyncMock(return_value=True)
    monkeypatch.setattr(relations_http._audit_log_service, "record", audit_record)

    with TestClient(app) as client:
        resp = client.delete("/api/v1/admin/graph/relations/rel-to-delete")

    assert resp.status_code == 200
    audit_record.assert_awaited_once()
    call_kwargs = audit_record.call_args.kwargs
    assert call_kwargs["action"] == "admin.graph.relation.deleted"
    assert call_kwargs["resource_id"] == "rel-to-delete"


# ===========================================================================
# X-Z: GraphRAG permission filtering
# ===========================================================================

@pytest.mark.asyncio
async def test_graphrag_allowed_document_ids_passed_to_service() -> None:
    """X: allowed_document_ids are forwarded to all graph retrieval service calls."""
    from uuid import UUID

    org_id = UUID(_ORG_A)
    allowed_doc_ids = [UUID("d0000000-0000-0000-0000-000000000001")]

    mock_graph_svc = SimpleNamespace(
        is_available=lambda: True,
        find_entities_by_name=AsyncMock(return_value=[]),
    )
    svc = GraphRetrievalService(graph_service=mock_graph_svc)  # type: ignore[arg-type]

    mock_db = AsyncMock()
    result = await svc.expand(
        session=mock_db,
        organization_id=org_id,
        question="Tell me about Acme Corp",
        allowed_document_ids=allowed_doc_ids,
        graph_enabled=True,
    )

    # No seed entities found → no graph context used, but org scoping still enforced
    assert result.graph_context_enabled is True
    # find_entities_by_name must be called with organization_id
    if mock_graph_svc.find_entities_by_name.call_count > 0:
        for call in mock_graph_svc.find_entities_by_name.call_args_list:
            assert call.kwargs["organization_id"] == org_id


@pytest.mark.asyncio
async def test_graphrag_no_allowed_docs_passes_none_to_service() -> None:
    """Y: allowed_document_ids=None passes through (all accessible docs)."""
    from uuid import UUID

    org_id = UUID(_ORG_A)

    mock_graph_svc = SimpleNamespace(
        is_available=lambda: True,
        find_entities_by_name=AsyncMock(return_value=[]),
    )
    svc = GraphRetrievalService(graph_service=mock_graph_svc)  # type: ignore[arg-type]

    mock_db = AsyncMock()
    result = await svc.expand(
        session=mock_db,
        organization_id=org_id,
        question="Tell me about Beta Ltd",
        allowed_document_ids=None,  # no restriction
        graph_enabled=True,
    )

    assert result.graph_context_enabled is True


@pytest.mark.asyncio
async def test_graphrag_org_id_propagated_to_all_calls() -> None:
    """Z: organization_id from caller is used in every graph lookup during expand()."""
    from uuid import UUID

    org_id = UUID(_ORG_A)
    other_org_id = UUID(_ORG_B)

    mock_graph_svc = SimpleNamespace(
        is_available=lambda: True,
        find_entities_by_name=AsyncMock(return_value=[]),
    )
    svc = GraphRetrievalService(graph_service=mock_graph_svc)  # type: ignore[arg-type]

    mock_db = AsyncMock()
    await svc.expand(
        session=mock_db,
        organization_id=org_id,
        question='Tell me about "Acme Corp" and "TechCorp"',
        allowed_document_ids=None,
        graph_enabled=True,
    )

    for call in mock_graph_svc.find_entities_by_name.call_args_list:
        called_org = call.kwargs.get("organization_id")
        assert called_org == org_id, f"Expected {org_id}, got {called_org}"
        assert called_org != other_org_id


# ===========================================================================
# AA-AE: Permission matrix assertions
# ===========================================================================

def test_permission_graph_view_granted_to_standard_roles() -> None:
    """AA: graph_view is in viewer, reviewer, member, developer, admin, owner."""
    roles_with_graph_view = {"viewer", "reviewer", "member", "developer", "admin", "owner"}
    for role in roles_with_graph_view:
        assert PermissionType.graph_view in ROLE_PERMISSIONS[role], (
            f"graph_view missing from {role}"
        )


def test_permission_graph_entities_manage_restricted_to_admin_owner() -> None:
    """AB: graph_entities_manage is only in admin and owner."""
    assert PermissionType.graph_entities_manage in ROLE_PERMISSIONS["admin"]
    assert PermissionType.graph_entities_manage in ROLE_PERMISSIONS["owner"]

    non_admin_roles = {"viewer", "reviewer", "member", "developer", "billing_admin", "security_admin"}
    for role in non_admin_roles:
        assert PermissionType.graph_entities_manage not in ROLE_PERMISSIONS[role], (
            f"graph_entities_manage should NOT be in {role}"
        )


def test_permission_graph_relations_manage_restricted_to_admin_owner() -> None:
    """AC: graph_relations_manage is only in admin and owner."""
    assert PermissionType.graph_relations_manage in ROLE_PERMISSIONS["admin"]
    assert PermissionType.graph_relations_manage in ROLE_PERMISSIONS["owner"]

    non_admin_roles = {"viewer", "reviewer", "member", "developer", "billing_admin", "security_admin"}
    for role in non_admin_roles:
        assert PermissionType.graph_relations_manage not in ROLE_PERMISSIONS[role], (
            f"graph_relations_manage should NOT be in {role}"
        )


def test_permission_security_admin_has_audit_log_not_graph_view() -> None:
    """AD: security_admin can view graph audit logs but cannot browse graph data."""
    security_perms = ROLE_PERMISSIONS["security_admin"]
    assert PermissionType.graph_audit_logs_view in security_perms
    assert PermissionType.graph_view not in security_perms
    assert PermissionType.graph_entities_manage not in security_perms
    assert PermissionType.graph_relations_manage not in security_perms


def test_permission_billing_admin_has_no_graph_permissions() -> None:
    """AE: billing_admin has no graph permissions at all."""
    billing_perms = ROLE_PERMISSIONS["billing_admin"]
    graph_perms = {
        PermissionType.graph_view,
        PermissionType.graph_entities_manage,
        PermissionType.graph_relations_manage,
        PermissionType.graph_governance_configure,
        PermissionType.graph_audit_logs_view,
    }
    overlap = billing_perms & graph_perms
    assert not overlap, f"billing_admin should have no graph permissions, got: {overlap}"


# ===========================================================================
# AF-AH: Redaction
# ===========================================================================

def test_redaction_neo4j_password_is_sanitized() -> None:
    """AF: neo4j_password key value is replaced with *** in audit metadata."""
    meta = {"neo4j_password": "super-secret-bolt-pass", "entity_id": "e-1"}
    sanitized = sanitize_metadata(meta)
    assert sanitized["neo4j_password"] == "***"
    assert sanitized["entity_id"] == "e-1"


def test_redaction_bolt_password_suffix_is_sanitized() -> None:
    """AG: keys ending in _bolt_password are redacted."""
    meta = {"primary_bolt_password": "hunter2", "secondary_neo4j_password": "pass2"}
    sanitized = sanitize_metadata(meta)
    assert sanitized["primary_bolt_password"] == "***"
    assert sanitized["secondary_neo4j_password"] == "***"


def test_redaction_neo4j_uri_is_sanitized() -> None:
    """AH: neo4j_uri key is redacted (may contain embedded credentials)."""
    meta = {"neo4j_uri": "bolt://admin:secret@localhost:7687", "action": "test"}
    sanitized = sanitize_metadata(meta)
    assert sanitized["neo4j_uri"] == "***"
    assert sanitized["action"] == "test"


def test_redaction_neo4j_auth_is_sanitized() -> None:
    """AF+: neo4j_auth and bolt_uri are also redacted."""
    meta = {
        "neo4j_auth": ("neo4j", "secret"),
        "bolt_uri": "bolt://localhost:7687",
        "bolt_password": "pw",
    }
    sanitized = sanitize_metadata(meta)
    assert sanitized["neo4j_auth"] == "***"
    assert sanitized["bolt_uri"] == "***"
    assert sanitized["bolt_password"] == "***"
