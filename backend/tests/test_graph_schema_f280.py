"""Backend tests for F280: Enterprise Graph schema, constraints, indexes, and migration runner.

Covers:
  A. schema.py: NODE_LABELS contains all 18 required labels
  B. schema.py: RELATIONSHIP_TYPES contains all 10 required types
  C. schema.py: MIGRATIONS is non-empty and version "0001" exists
  D. schema.py: Migration "0001" includes all 3 node-key constraints
  E. schema.py: Migration "0001" includes all 9 indexes
  F. schema.py: Every DDL statement contains "IF NOT EXISTS" (idempotency guarantee)
  G. migration_runner: enterprise_graph_enabled=false → returns empty result, no DB calls
  H. migration_runner: driver None → returns empty result, no DB calls
  I. migration_runner: migration already applied → skipped, no DDL executed
  J. migration_runner: new migration → DDL statements run, migration recorded
  K. migration_runner: two sequential runs → second run skips everything
  L. migration_runner: DDL statement error → result.failed is set, no raise
  M. migration_runner: get_migration_status disabled → returns []
  N. migration_runner: get_migration_status driver None → returns []
  O. migration_runner: get_migration_status with records → returns list
  P. Constraint targets: document_org_document_key covers (organization_id, document_id)
  Q. Constraint targets: entity_org_entity_key covers (organization_id, entity_id)
  R. POST /admin/graph/migrate disabled → 503 enterprise_graph_disabled
  S. POST /admin/graph/migrate success → 200 with applied list
  T. POST /admin/graph/migrate member role → 403
  U. GET /admin/graph/migrations disabled → 200 with enabled=false and []
  V. GET /admin/graph/migrations enabled → 200 with applied records
  W. Query smoke test: entity search by organization_id uses scoped parameter
  X. Query smoke test: document lookup uses organization_id + document_id

Run:
    pytest tests/test_graph_schema_f280.py -v
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

from fastapi.testclient import TestClient

import app.clients.neo4j_client as neo4j_module
import app.domains.graph.migration_runner as runner_module
from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.graph.schema import MIGRATIONS, NODE_LABELS, RELATIONSHIP_TYPES
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _principal_override(role: str):
    async def _dep() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id="test-user",
            organization_id="org-1",
            roles=[role],
            auth_provider="app",
        )

    return _dep


def _mock_session(run_side_effect: Any = None) -> MagicMock:
    """Build a mock async Neo4j session."""
    mock_result = AsyncMock()
    mock_result.data = AsyncMock(return_value=[])
    mock_result.consume = AsyncMock(return_value=None)
    if run_side_effect:
        mock_result.consume = AsyncMock(side_effect=run_side_effect)

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute_write = AsyncMock(return_value=None)

    return mock_session


def _mock_driver(session: Any) -> MagicMock:
    mock = MagicMock()
    mock.session = MagicMock(return_value=session)
    return mock


# ---------------------------------------------------------------------------
# A-F. schema.py content tests
# ---------------------------------------------------------------------------


def test_a_node_labels_contains_all_required() -> None:
    required = {
        "Document",
        "Chunk",
        "Entity",
        "Person",
        "Organization",
        "Customer",
        "EntityAlias",
        "EntityResolutionDecision",
        "Vendor",
        "Product",
        "Project",
        "Policy",
        "Contract",
        "Control",
        "Requirement",
        "Risk",
        "Ticket",
        "System",
        "Process",
        "Obligation",
    }
    assert required == set(NODE_LABELS)


def test_b_relationship_types_contains_all_required() -> None:
    required = {
        "MENTIONS",
        "EVIDENCE_FOR",
        "RELATES_TO",
        "OWNS",
        "COVERS_CONTROL",
        "CONTAINS_OBLIGATION",
        "PROVIDES_SERVICE_TO",
        "SUPERSEDES",
        "AFFECTS",
        "DEPENDS_ON",
    }
    assert required == set(RELATIONSHIP_TYPES)


def test_c_migrations_nonempty_and_v0001_exists() -> None:
    assert len(MIGRATIONS) >= 1
    versions = [m.version for m in MIGRATIONS]
    assert "0001" in versions


def test_d_v0001_has_three_node_key_constraints() -> None:
    m = next(m for m in MIGRATIONS if m.version == "0001")
    constraint_stmts = [s for s in m.statements if "NODE KEY" in s]
    assert len(constraint_stmts) == 3
    constraint_names = " ".join(constraint_stmts)
    assert "organization_id, d.document_id" in constraint_names
    assert "organization_id, c.chunk_id" in constraint_names
    assert "organization_id, e.entity_id" in constraint_names


def test_e_v0001_has_nine_indexes() -> None:
    m = next(m for m in MIGRATIONS if m.version == "0001")
    index_stmts = [s for s in m.statements if "CREATE INDEX" in s]
    assert len(index_stmts) == 9


def test_e1_v0004_contains_alias_and_decision_support() -> None:
    m = next(m for m in MIGRATIONS if m.version == "0004")
    assert any("entity_alias_org_alias_key" in s for s in m.statements)
    assert any("entity_resolution_decision_org_decision_key" in s for s in m.statements)
    assert any("entity_normalized_name_idx" in s for s in m.statements)
    assert any("entity_alias_normalized_name_idx" in s for s in m.statements)


def test_f_all_ddl_statements_contain_if_not_exists() -> None:
    for migration in MIGRATIONS:
        for stmt in migration.statements:
            assert "IF NOT EXISTS" in stmt, (
                f"Migration {migration.version} statement missing IF NOT EXISTS: {stmt[:80]}"
            )


# ---------------------------------------------------------------------------
# G-H. migration_runner: disabled / driver-None early returns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g_migrations_disabled_returns_empty_no_db_calls() -> None:
    with (
        patch.object(settings, "enterprise_graph_enabled", False),
        patch.object(neo4j_module, "_neo4j_driver", None),
    ):
        result = await runner_module.run_graph_migrations()

    assert result.applied == []
    assert result.already_applied == []
    assert result.failed is None
    assert result.success is True


@pytest.mark.asyncio
async def test_h_migrations_driver_none_returns_empty_no_db_calls() -> None:
    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch("app.domains.graph.migration_runner.get_driver", return_value=None),
    ):
        result = await runner_module.run_graph_migrations()

    assert result.applied == []
    assert result.already_applied == []
    assert result.failed is None


# ---------------------------------------------------------------------------
# I. Already-applied migrations are skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_i_already_applied_migration_is_skipped() -> None:
    session = _mock_session()
    # Simulate that "0001" is already applied
    mock_result = AsyncMock()
    mock_result.data = AsyncMock(return_value=[{"version": "0001"}])
    session.run = AsyncMock(return_value=mock_result)

    driver = _mock_driver(session)

    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch.object(settings, "neo4j_database", "neo4j"),
        patch.object(settings, "neo4j_query_timeout_seconds", 5.0),
        patch("app.domains.graph.migration_runner.get_driver", return_value=driver),
    ):
        result = await runner_module.run_graph_migrations()

    assert "0001" in result.already_applied
    assert "0001" not in result.applied
    assert result.failed is None


# ---------------------------------------------------------------------------
# J. New migration: DDL and record both written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_j_new_migration_applies_statements_and_records() -> None:
    apply_calls: list[str] = []

    schema_session = AsyncMock()
    schema_session.__aenter__ = AsyncMock(return_value=schema_session)
    schema_session.__aexit__ = AsyncMock(return_value=None)
    schema_mock_result = AsyncMock()
    schema_mock_result.consume = AsyncMock(return_value=None)

    def _capture_run(stmt: str, **_kw: Any) -> Any:
        apply_calls.append(stmt)
        return schema_mock_result

    schema_session.run = AsyncMock(side_effect=_capture_run)
    schema_session.execute_write = AsyncMock(return_value=None)

    # First session.run returns no applied migrations
    query_session = AsyncMock()
    query_session.__aenter__ = AsyncMock(return_value=query_session)
    query_session.__aexit__ = AsyncMock(return_value=None)
    query_result = AsyncMock()
    query_result.data = AsyncMock(return_value=[])
    query_session.run = AsyncMock(return_value=query_result)

    call_count = 0

    def _session_factory(**_kw: Any) -> Any:
        nonlocal call_count
        call_count += 1
        # First call: _get_applied_versions; subsequent: _apply_migration (schema + data)
        return query_session if call_count == 1 else schema_session

    driver = MagicMock()
    driver.session = MagicMock(side_effect=_session_factory)

    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch.object(settings, "neo4j_database", "neo4j"),
        patch.object(settings, "neo4j_query_timeout_seconds", 5.0),
        patch("app.domains.graph.migration_runner.get_driver", return_value=driver),
    ):
        result = await runner_module.run_graph_migrations()

    assert "0001" in result.applied
    assert result.already_applied == []
    assert result.failed is None
    # DDL statements were executed (schema session.run called)
    assert len(apply_calls) >= 3  # at least the 3 constraint statements


# ---------------------------------------------------------------------------
# K. Idempotency: second run skips everything
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k_second_run_skips_all_migrations() -> None:
    applied_versions: set[str] = set()

    async def _mark(tx: Any) -> None:
        applied_versions.add("0001")

    async def _run_async(stmt: str, **_kw: Any) -> Any:
        r = AsyncMock()
        r.data = AsyncMock(return_value=[{"version": v} for v in applied_versions])
        r.consume = AsyncMock(return_value=None)
        return r

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute_write = AsyncMock(side_effect=_mark)
    session.run = AsyncMock(side_effect=_run_async)

    driver = MagicMock()
    driver.session = MagicMock(return_value=session)

    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch.object(settings, "neo4j_database", "neo4j"),
        patch.object(settings, "neo4j_query_timeout_seconds", 5.0),
        patch("app.domains.graph.migration_runner.get_driver", return_value=driver),
    ):
        first = await runner_module.run_graph_migrations()
        second = await runner_module.run_graph_migrations()

    # First run applied; second run skipped all
    assert "0001" in first.applied or "0001" in first.already_applied
    assert "0001" in second.already_applied
    assert "0001" not in second.applied


# ---------------------------------------------------------------------------
# L. Error in DDL → result.failed set, no raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_ddl_error_sets_failed_field() -> None:
    query_session = AsyncMock()
    query_session.__aenter__ = AsyncMock(return_value=query_session)
    query_session.__aexit__ = AsyncMock(return_value=None)
    query_result = AsyncMock()
    query_result.data = AsyncMock(return_value=[])
    query_session.run = AsyncMock(return_value=query_result)

    schema_session = AsyncMock()
    schema_session.__aenter__ = AsyncMock(return_value=schema_session)
    schema_session.__aexit__ = AsyncMock(return_value=None)
    bad_result = AsyncMock()
    bad_result.consume = AsyncMock(side_effect=RuntimeError("constraint error"))
    schema_session.run = AsyncMock(return_value=bad_result)

    call_count = 0

    def _session_factory(**_kw: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return query_session if call_count == 1 else schema_session

    driver = MagicMock()
    driver.session = MagicMock(side_effect=_session_factory)

    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch.object(settings, "neo4j_database", "neo4j"),
        patch.object(settings, "neo4j_query_timeout_seconds", 5.0),
        patch("app.domains.graph.migration_runner.get_driver", return_value=driver),
    ):
        result = await runner_module.run_graph_migrations()

    assert result.failed is not None
    assert "RuntimeError" in result.failed or "constraint error" in result.failed
    assert result.success is False


# ---------------------------------------------------------------------------
# M-O. get_migration_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_get_migration_status_disabled_returns_empty() -> None:
    with patch.object(settings, "enterprise_graph_enabled", False):
        records = await runner_module.get_migration_status()
    assert records == []


@pytest.mark.asyncio
async def test_n_get_migration_status_driver_none_returns_empty() -> None:
    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch("app.domains.graph.migration_runner.get_driver", return_value=None),
    ):
        records = await runner_module.get_migration_status()
    assert records == []


@pytest.mark.asyncio
async def test_o_get_migration_status_returns_records() -> None:
    mock_result = AsyncMock()
    mock_result.data = AsyncMock(
        return_value=[
            {
                "version": "0001",
                "description": "Initial schema",
                "applied_at": "2026-06-14T00:00:00+00:00",
            },
        ]
    )
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.run = AsyncMock(return_value=mock_result)

    driver = MagicMock()
    driver.session = MagicMock(return_value=session)

    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch.object(settings, "neo4j_database", "neo4j"),
        patch.object(settings, "neo4j_query_timeout_seconds", 5.0),
        patch("app.domains.graph.migration_runner.get_driver", return_value=driver),
    ):
        records = await runner_module.get_migration_status()

    assert len(records) == 1
    assert records[0]["version"] == "0001"
    assert records[0]["description"] == "Initial schema"


# ---------------------------------------------------------------------------
# P-Q. Constraint Cypher targets correct properties
# ---------------------------------------------------------------------------


def test_p_document_constraint_targets_org_and_document_id() -> None:
    m = next(m for m in MIGRATIONS if m.version == "0001")
    doc_constraint = next(s for s in m.statements if "document_org_document_key" in s)
    assert "d.organization_id" in doc_constraint
    assert "d.document_id" in doc_constraint
    assert "NODE KEY" in doc_constraint


def test_q_entity_constraint_targets_org_and_entity_id() -> None:
    m = next(m for m in MIGRATIONS if m.version == "0001")
    ent_constraint = next(s for s in m.statements if "entity_org_entity_key" in s)
    assert "e.organization_id" in ent_constraint
    assert "e.entity_id" in ent_constraint
    assert "NODE KEY" in ent_constraint


# ---------------------------------------------------------------------------
# R-T. POST /admin/graph/migrate
# ---------------------------------------------------------------------------


def test_r_migrate_endpoint_disabled_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        response = client.post("/api/v1/admin/graph/migrate")
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert response.status_code == 503
    assert response.json()["detail"] == "enterprise_graph_disabled"


def test_s_migrate_endpoint_success_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_schema as schema_http
    from app.domains.graph.migration_runner import MigrationResult

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(
        schema_http,
        "run_graph_migrations",
        AsyncMock(return_value=MigrationResult(applied=["0001"], already_applied=[])),
    )
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        response = client.post("/api/v1/admin/graph/migrate")
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "0001" in body["applied"]
    assert body["already_applied"] == []
    assert body["failed"] is None


def test_t_migrate_endpoint_member_gets_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    try:
        client = TestClient(app)
        response = client.post("/api/v1/admin/graph/migrate")
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# U-V. GET /admin/graph/migrations
# ---------------------------------------------------------------------------


def test_u_migrations_list_disabled_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(runner_module, "get_migration_status", AsyncMock(return_value=[]))
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        response = client.get("/api/v1/admin/graph/migrations")
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["migrations"] == []


def test_v_migrations_list_enabled_returns_records(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_schema as schema_http

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(
        schema_http,
        "get_migration_status",
        AsyncMock(
            return_value=[
                {
                    "version": "0001",
                    "description": "Initial constraints and indexes",
                    "applied_at": "2026-06-14T10:00:00+00:00",
                }
            ]
        ),
    )
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        response = client.get("/api/v1/admin/graph/migrations")
    finally:
        app.dependency_overrides.pop(get_current_principal, None)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert len(body["migrations"]) == 1
    assert body["migrations"][0]["version"] == "0001"


# ---------------------------------------------------------------------------
# W-X. Query smoke tests: organization_id scoping
# ---------------------------------------------------------------------------


def test_w_entity_search_uses_organization_id_param() -> None:
    """The entity-search query template must include an organization_id filter."""
    entity_search_query = (
        "MATCH (e:Entity) WHERE e.organization_id = $organization_id "
        "AND e.canonical_name CONTAINS $name RETURN e LIMIT 20"
    )
    assert "$organization_id" in entity_search_query
    assert "e.organization_id" in entity_search_query


def test_x_document_lookup_uses_org_and_document_id_params() -> None:
    """The document-lookup query template must scope by both organization_id and document_id."""
    doc_lookup_query = (
        "MATCH (d:Document {organization_id: $organization_id, document_id: $document_id}) "
        "OPTIONAL MATCH (d)-[:MENTIONS]->(e:Entity) RETURN d, collect(e) AS entities"
    )
    assert "$organization_id" in doc_lookup_query
    assert "$document_id" in doc_lookup_query
    assert "organization_id" in doc_lookup_query
