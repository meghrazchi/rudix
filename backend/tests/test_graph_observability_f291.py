"""Backend tests for F291: Graph observability, quality dashboard, and rollout controls.

Covers:
  A. GET /admin/graph/observability — empty org returns zero metrics, graph_enabled reflects config
  B. GET /admin/graph/observability — role guard: member gets 403
  C. GET /admin/graph/observability — extraction metrics counted from document graph_extraction_status
  D. GET /admin/graph/observability — success_rate computed from completed vs failed documents
  E. GET /admin/graph/observability — extraction telemetry_missing when no docs in range
  F. GET /admin/graph/observability — query metrics counted from AuditLog with graphrag_used=True
  G. GET /admin/graph/observability — query failure_rate computed from graphrag_failure flag
  H. GET /admin/graph/observability — fallback_rate computed from graphrag_fallback flag
  I. GET /admin/graph/observability — avg_expansion_size averaged across graphrag entries
  J. GET /admin/graph/observability — query telemetry_missing when no graphrag audit logs exist
  K. GET /admin/graph/observability — from/to query params filter the time range
  L. GET /admin/graph/observability — from > to returns 400
  M. GET /admin/graph/observability — org isolation: another org's docs not counted
  N. GET /admin/graph/observability — alerts emitted when extraction failure rate exceeds threshold
  O. GET /admin/graph/observability — alert emitted when graphrag fallback rate exceeds threshold
  P. GET /admin/graph/observability — no alerts when all metrics within threshold
  Q. GET /admin/graph/observability — neo4j_reachable=False when enterprise_graph_enabled=False
  R. GET /admin/graph/observability — response includes range and generated_at fields
  S. Feature flags — graph_extraction and graph_explorer flags present in GET /admin/feature-flags
  T. Feature flags — PUT /admin/feature-flags/graph_extraction toggles per-org
  U. Feature flags — PUT /admin/feature-flags/graph_explorer toggles per-org

Run:
    pytest tests/test_graph_observability_f291.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog, UsageEvent
from app.models.user import User

API_PREFIX = settings.api_prefix
GRAPH_OBSERVABILITY_PATH = f"{API_PREFIX}/admin/graph/observability"
FEATURE_FLAGS_PATH = f"{API_PREFIX}/admin/feature-flags"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def gobs_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    # Disable Neo4j so entity/relation metrics degrade gracefully in tests.
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


def _make_token(user_id: str, org_id: str, role: str = OrganizationRole.admin.value) -> str:
    return create_app_access_token(
        subject=user_id,
        organization_id=org_id,
        role=role,
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_org_user(db: AsyncSession, role: str = OrganizationRole.admin.value) -> dict:
    slug = f"gobs-{uuid4().hex[:8]}"
    org = Organization(name=f"GObs Org {slug}", slug=slug)
    db.add(org)
    await db.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"gobs-{uuid4().hex[:8]}",
        email=f"gobs-{uuid4().hex[:6]}@test.com",
        display_name="GObs User",
    )
    db.add(user)
    await db.flush()

    member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    db.add(member)
    await db.flush()

    token = _make_token(str(user.id), str(org.id), role)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _doc(
    org_id: str | UUID,
    uploaded_by: str | UUID,
    graph_status: str = "completed",
) -> Document:
    return Document(
        organization_id=UUID(str(org_id)),
        uploaded_by_user_id=UUID(str(uploaded_by)),
        filename=f"doc-{uuid4().hex[:6]}.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"graph/{uuid4().hex[:8]}.pdf",
        status="indexed",
        graph_extraction_status=graph_status,
    )


def _graphrag_log(
    org_id: str | UUID,
    *,
    used: bool = True,
    failure: bool = False,
    fallback: bool = False,
    expansion_size: int | None = 5,
    latency_ms: int | None = 250,
) -> UsageEvent:
    meta: dict = {
        "graph_context_enabled": used or failure or fallback,
        "graph_context_used": used and not fallback and not failure,
        "graph_context_unavailable": failure,
        "graph_context_reason": "neo4j_unavailable" if failure else None,
    }
    if expansion_size is not None:
        meta["graphrag_expansion_size"] = expansion_size
    if latency_ms is not None:
        meta["answer_latency_ms"] = latency_ms
        meta["latency_ms"] = latency_ms
    return UsageEvent(
        organization_id=UUID(str(org_id)),
        event_type="chat.completion",
        metadata_json=meta,
    )


# ---------------------------------------------------------------------------
# A. Empty org returns zero metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_org_returns_zero_extraction_metrics(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["extraction"]["total_runs"] == 0
    assert data["extraction"]["telemetry_missing"] is True
    assert data["queries"]["graphrag_queries"] == 0
    assert data["queries"]["telemetry_missing"] is True
    assert data["graph_enabled"] is False
    assert data["neo4j_reachable"] is False


# ---------------------------------------------------------------------------
# B. Role guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_role_is_forbidden(gobs_client: AsyncClient, db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session, role=OrganizationRole.member.value)
    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# C. Extraction metrics counted from document graph_extraction_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_metrics_counted_from_documents(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    for status in ("completed", "completed", "failed", "skipped", "extracting"):
        doc = _doc(org_id, user_id, graph_status=status)
        db_session.add(doc)
    await db_session.flush()

    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    assert resp.status_code == 200
    ext = resp.json()["extraction"]
    assert ext["total_runs"] == 5
    assert ext["succeeded"] == 2
    assert ext["failed"] == 1
    assert ext["skipped"] == 1
    assert ext["running"] == 1
    assert ext["telemetry_missing"] is False


# ---------------------------------------------------------------------------
# D. success_rate computed from completed vs failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_success_rate_excludes_running(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id, user_id = ctx["org_id"], ctx["user_id"]

    for status in ("completed", "completed", "failed"):
        db_session.add(_doc(org_id, user_id, graph_status=status))
    await db_session.flush()

    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    data = resp.json()["extraction"]
    # success_rate = completed / (completed + failed) = 2/3
    assert abs(data["success_rate"] - 2 / 3) < 0.001


# ---------------------------------------------------------------------------
# E. telemetry_missing when no docs updated in range
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_telemetry_missing_outside_range(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    # No docs added — range has no data
    resp = await gobs_client.get(
        GRAPH_OBSERVABILITY_PATH,
        headers=_auth(ctx["token"]),
        params={"from": "2020-01-01", "to": "2020-01-31"},
    )
    assert resp.status_code == 200
    assert resp.json()["extraction"]["telemetry_missing"] is True


# ---------------------------------------------------------------------------
# F. Query metrics counted from AuditLog with graphrag_used=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_metrics_counted_from_audit_log(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    for _ in range(3):
        db_session.add(_graphrag_log(org_id, used=True))
    # Non-graphrag chat audit — should not be counted
    db_session.add(
        AuditLog(
            organization_id=UUID(str(org_id)),
            action="chat.answer",
            resource_type="chat_session",
            metadata_json={"graphrag_used": False},
        )
    )
    await db_session.flush()

    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    q = resp.json()["queries"]
    assert q["graphrag_queries"] == 3
    assert q["graphrag_failures"] == 0
    assert q["telemetry_missing"] is False


# ---------------------------------------------------------------------------
# G. failure_rate from graphrag_failure flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_failure_rate_computed(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_graphrag_log(org_id, used=True, failure=False))
    db_session.add(_graphrag_log(org_id, used=True, failure=True))
    await db_session.flush()

    q = (await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))).json()[
        "queries"
    ]
    assert q["graphrag_failures"] == 1
    assert abs(q["failure_rate"] - 0.5) < 0.001


# ---------------------------------------------------------------------------
# H. fallback_rate from graphrag_fallback flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_fallback_rate_computed(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_graphrag_log(org_id, used=True, fallback=True))
    db_session.add(_graphrag_log(org_id, used=True, fallback=True))
    db_session.add(_graphrag_log(org_id, used=True, fallback=False))
    await db_session.flush()

    q = (await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))).json()[
        "queries"
    ]
    assert q["fallback_to_rag"] == 2
    assert abs(q["fallback_rate"] - 2 / 3) < 0.001


# ---------------------------------------------------------------------------
# I. avg_expansion_size averaged across graphrag entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_avg_expansion_size_averaged(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_graphrag_log(org_id, used=True, expansion_size=4))
    db_session.add(_graphrag_log(org_id, used=True, expansion_size=8))
    await db_session.flush()

    q = (await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))).json()[
        "queries"
    ]
    assert abs(q["avg_expansion_size"] - 6.0) < 0.001


# ---------------------------------------------------------------------------
# J1. avg latency and p95 computed across GraphRAG usage events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_latency_metrics_computed(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_graphrag_log(org_id, used=True, latency_ms=100))
    db_session.add(_graphrag_log(org_id, used=True, latency_ms=200))
    db_session.add(_graphrag_log(org_id, used=True, latency_ms=300))
    await db_session.flush()

    q = (await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))).json()[
        "queries"
    ]
    assert abs(q["avg_latency_ms"] - 200.0) < 0.001
    assert q["p95_latency_ms"] is not None
    assert q["p95_latency_ms"] >= 200.0
    assert q["cypher_failures"] == 0


# ---------------------------------------------------------------------------
# J2. Failure rate includes Neo4j/Cypher unavailable events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_cypher_failures_computed(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_graphrag_log(org_id, used=True, failure=True, latency_ms=120))
    db_session.add(_graphrag_log(org_id, used=True, latency_ms=140))
    await db_session.flush()

    q = (await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))).json()[
        "queries"
    ]
    assert q["graphrag_queries"] == 2
    assert q["graphrag_failures"] == 1
    assert q["cypher_failures"] == 1
    assert abs(q["cypher_failure_rate"] - 0.5) < 0.001


# ---------------------------------------------------------------------------
# J. query telemetry_missing when no graphrag audit logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_telemetry_missing_no_graphrag_logs(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]
    # Log a chat event without graphrag_used
    db_session.add(
        AuditLog(
            organization_id=UUID(str(org_id)),
            action="chat.answer",
            resource_type="chat_session",
            metadata_json={"foo": "bar"},
        )
    )
    await db_session.flush()

    q = (await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))).json()[
        "queries"
    ]
    assert q["telemetry_missing"] is True


# ---------------------------------------------------------------------------
# K. from/to query params filter the time range
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_date_range_filter(gobs_client: AsyncClient, db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session)
    # No documents in 2020 range — should be 0
    resp = await gobs_client.get(
        GRAPH_OBSERVABILITY_PATH,
        headers=_auth(ctx["token"]),
        params={"from": "2020-06-01", "to": "2020-06-30"},
    )
    assert resp.status_code == 200
    assert resp.json()["extraction"]["total_runs"] == 0


# ---------------------------------------------------------------------------
# L. from > to returns 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_date_range_returns_400(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await gobs_client.get(
        GRAPH_OBSERVABILITY_PATH,
        headers=_auth(ctx["token"]),
        params={"from": "2026-06-30", "to": "2026-06-01"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# M. Org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_isolation_extraction_metrics(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx_a = await _make_org_user(db_session)
    ctx_b = await _make_org_user(db_session)

    # Add a completed doc to org B only
    db_session.add(_doc(ctx_b["org_id"], ctx_b["user_id"], graph_status="completed"))
    await db_session.flush()

    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx_a["token"]))
    assert resp.json()["extraction"]["total_runs"] == 0


# ---------------------------------------------------------------------------
# N. Alert when extraction failure rate exceeds threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_raised_for_high_extraction_failure_rate(
    monkeypatch: pytest.MonkeyPatch,
    gobs_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "graph_alert_extraction_failure_rate_max", 0.2)
    ctx = await _make_org_user(db_session)
    org_id, user_id = ctx["org_id"], ctx["user_id"]

    # 1 completed, 3 failed → failure_rate = 0.75 > 0.2
    db_session.add(_doc(org_id, user_id, graph_status="completed"))
    for _ in range(3):
        db_session.add(_doc(org_id, user_id, graph_status="failed"))
    await db_session.flush()

    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    alerts = resp.json()["alerts"]
    metrics = [a["metric"] for a in alerts]
    assert "extraction_failure_rate" in metrics


# ---------------------------------------------------------------------------
# O. Alert when graphrag fallback rate exceeds threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_raised_for_high_graphrag_fallback_rate(
    monkeypatch: pytest.MonkeyPatch,
    gobs_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "graph_alert_graphrag_fallback_rate_max", 0.2)
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    # 4 fallbacks out of 5 → 80% > 20%
    for _ in range(4):
        db_session.add(_graphrag_log(org_id, used=True, fallback=True))
    db_session.add(_graphrag_log(org_id, used=True, fallback=False))
    await db_session.flush()

    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    alerts = resp.json()["alerts"]
    assert any(a["metric"] == "graphrag_fallback_rate" for a in alerts)


# ---------------------------------------------------------------------------
# P. No alerts when all metrics within threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_alerts_when_metrics_within_threshold(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    # Empty org — no data, no alerts (missing telemetry doesn't trigger alerts)
    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    assert resp.json()["alerts"] == []


# ---------------------------------------------------------------------------
# Q. neo4j_reachable=False when enterprise_graph_enabled=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_neo4j_reachable_false_when_graph_disabled(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await gobs_client.get(GRAPH_OBSERVABILITY_PATH, headers=_auth(ctx["token"]))
    data = resp.json()
    assert data["graph_enabled"] is False
    assert data["neo4j_reachable"] is False


# ---------------------------------------------------------------------------
# R. Response includes range and generated_at
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_includes_range_and_generated_at(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await gobs_client.get(
        GRAPH_OBSERVABILITY_PATH,
        headers=_auth(ctx["token"]),
        params={"from": "2026-06-01", "to": "2026-06-14"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["range"]["from"] == "2026-06-01"
    assert data["range"]["to"] == "2026-06-14"
    assert "generated_at" in data
    assert data["organization_id"] == ctx["org_id"]


# ---------------------------------------------------------------------------
# R1. Trend series includes daily quality metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_includes_trend_points(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]
    user_id = ctx["user_id"]

    db_session.add(_doc(org_id, user_id, graph_status="completed"))
    db_session.add(_doc(org_id, user_id, graph_status="failed"))
    db_session.add(_graphrag_log(org_id, used=True, latency_ms=120))
    db_session.add(_graphrag_log(org_id, used=True, failure=True, latency_ms=220))
    await db_session.flush()

    resp = await gobs_client.get(
        GRAPH_OBSERVABILITY_PATH,
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    trends = resp.json()["trends"]
    assert len(trends) >= 1
    today = trends[-1]
    assert today["extraction_runs"] >= 2
    assert today["graphrag_queries"] >= 2
    assert today["cypher_failures"] >= 1


# ---------------------------------------------------------------------------
# S. Feature flags — graph_extraction and graph_explorer present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_feature_flags_present_in_list(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session, role=OrganizationRole.owner.value)
    resp = await gobs_client.get(FEATURE_FLAGS_PATH, headers=_auth(ctx["token"]))
    assert resp.status_code == 200
    flag_names = [f["name"] for f in resp.json()["flags"]]
    assert "graph_extraction" in flag_names
    assert "graph_explorer" in flag_names
    assert "graph_rag" in flag_names


# ---------------------------------------------------------------------------
# T. PUT /admin/feature-flags/graph_extraction toggles per-org
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_extraction_flag_can_be_toggled(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session, role=OrganizationRole.owner.value)
    resp = await gobs_client.put(
        f"{FEATURE_FLAGS_PATH}/graph_extraction",
        headers=_auth(ctx["token"]),
        json={"enabled": True, "reason": "test rollout"},
    )
    assert resp.status_code == 200
    flag = resp.json()["flag"]
    assert flag["name"] == "graph_extraction"
    assert flag["enabled"] is True
    assert flag["has_org_override"] is True


# ---------------------------------------------------------------------------
# U. PUT /admin/feature-flags/graph_explorer toggles per-org
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_explorer_flag_can_be_toggled(
    gobs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session, role=OrganizationRole.owner.value)
    resp = await gobs_client.put(
        f"{FEATURE_FLAGS_PATH}/graph_explorer",
        headers=_auth(ctx["token"]),
        json={"enabled": False, "reason": "disable for trial org"},
    )
    assert resp.status_code == 200
    flag = resp.json()["flag"]
    assert flag["name"] == "graph_explorer"
    assert flag["enabled"] is False
    assert flag["has_org_override"] is True
