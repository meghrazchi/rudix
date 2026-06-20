"""Backend tests for F155: Production observability dashboard.

Covers:
  A. GET /admin/observability — empty org returns all-zero metrics
  B. GET /admin/observability — role guard: member/viewer get 403
  C. GET /admin/observability — api_metrics counted from audit logs
  D. GET /admin/observability — error_rate computed from failed audit log results
  E. GET /admin/observability — telemetry_missing=True when no audit logs
  F. GET /admin/observability — llm_metrics counted from usage events with model_name
  G. GET /admin/observability — llm error rate detects error metadata flag
  H. GET /admin/observability — llm top_models sorted by count descending
  I. GET /admin/observability — indexing_metrics from pipeline usage events
  J. GET /admin/observability — indexing success_rate excludes failed pipeline events
  K. GET /admin/observability — storage_metrics counts documents by status
  L. GET /admin/observability — from/to query params filter the time range
  M. GET /admin/observability — from > to returns 400
  N. GET /admin/observability — org isolation: audit logs from another org not counted
  O. GET /admin/observability — response includes generated_at and organization_id

Run:
    pytest tests/test_observability_f155.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def obs_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
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
        user_id=user_id,
        organization_id=org_id,
        role=role,
        secret=SecretStr("test-secret"),
        issuer="rudix-test",
        audience="rudix-test-audience",
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_org_user(db: AsyncSession, role: str = OrganizationRole.admin.value) -> dict:
    slug = f"obs-org-{uuid4().hex[:8]}"
    org = Organization(name=f"Obs Org {slug}", slug=slug)
    db.add(org)
    await db.flush()

    user = User(email=f"obs-{uuid4().hex[:6]}@test.com", display_name="Obs User")
    db.add(user)
    await db.flush()

    member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    db.add(member)
    await db.flush()

    token = _make_token(str(user.id), str(org.id), role)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _audit_log(org_id, result: str = "success", metadata: dict | None = None) -> AuditLog:
    return AuditLog(
        organization_id=org_id,
        action="test.action",
        resource_type="document",
        metadata_json={"result": result, **(metadata or {})},
    )


def _usage_event(
    org_id,
    event_type: str = "chat.answer",
    model_name: str | None = "gpt-4o",
    metadata: dict | None = None,
) -> UsageEvent:
    return UsageEvent(
        organization_id=org_id,
        event_type=event_type,
        model_name=model_name,
        input_tokens=10,
        output_tokens=20,
        cost_usd=Decimal("0.001"),
        metadata_json=metadata or {},
    )


def _document(org_id, uploaded_by, status: str = "indexed", chunk_count: int = 5) -> Document:
    return Document(
        organization_id=org_id,
        uploaded_by_user_id=uploaded_by,
        filename=f"doc-{uuid4().hex[:6]}.pdf",
        file_type="pdf",
        file_size_bytes=1024,
        status=status,
        chunk_count=chunk_count if status == "indexed" else None,
    )


# ---------------------------------------------------------------------------
# A. Empty org returns all-zero metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_org_returns_zero_metrics(
    obs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_metrics"]["total_requests"] == 0
    assert data["api_metrics"]["telemetry_missing"] is True
    assert data["llm_metrics"]["total_events"] == 0
    assert data["llm_metrics"]["telemetry_missing"] is True
    assert data["indexing_metrics"]["total_jobs"] == 0
    assert data["storage_metrics"]["total_documents"] == 0


# ---------------------------------------------------------------------------
# B. Role guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_role_forbidden(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session, role=OrganizationRole.member.value)
    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_role_forbidden(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    ctx = await _make_org_user(db_session, role=OrganizationRole.viewer.value)
    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# C. api_metrics total_requests counts audit logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_metrics_total_requests(
    obs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    from uuid import UUID

    org_id = UUID(ctx["org_id"])
    for _ in range(3):
        db_session.add(_audit_log(org_id, result="success"))
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    assert resp.status_code == 200
    assert resp.json()["api_metrics"]["total_requests"] == 3


# ---------------------------------------------------------------------------
# D. error_rate computed from failed audit logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_error_rate(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    from uuid import UUID

    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])
    db_session.add(_audit_log(org_id, result="success"))
    db_session.add(_audit_log(org_id, result="failed"))
    db_session.add(_audit_log(org_id, result="error"))
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    assert resp.status_code == 200
    api = resp.json()["api_metrics"]
    assert api["total_requests"] == 3
    assert api["failed_requests"] == 2
    assert abs(api["error_rate"] - 2 / 3) < 1e-6


# ---------------------------------------------------------------------------
# E. telemetry_missing=True when no audit logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_telemetry_missing_when_no_logs(
    obs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    assert resp.json()["api_metrics"]["telemetry_missing"] is True


# ---------------------------------------------------------------------------
# F. llm_metrics counts usage events with model_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_metrics_total_events(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    from uuid import UUID

    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])
    db_session.add(_usage_event(org_id, model_name="gpt-4o"))
    db_session.add(_usage_event(org_id, model_name="gpt-4o"))
    db_session.add(_usage_event(org_id, model_name=None))
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    llm = resp.json()["llm_metrics"]
    assert llm["total_events"] == 2
    assert llm["telemetry_missing"] is False


# ---------------------------------------------------------------------------
# G. LLM error rate detects error metadata flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_error_rate(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    from uuid import UUID

    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])
    db_session.add(_usage_event(org_id, metadata={}))
    db_session.add(_usage_event(org_id, metadata={"error": "timeout"}))
    db_session.add(_usage_event(org_id, metadata={"status": "failed"}))
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    llm = resp.json()["llm_metrics"]
    assert llm["failed_events"] == 2
    assert abs(llm["error_rate"] - 2 / 3) < 1e-6


# ---------------------------------------------------------------------------
# H. llm top_models sorted by count descending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_top_models_sorted(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    from uuid import UUID

    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])
    for _ in range(3):
        db_session.add(_usage_event(org_id, model_name="gpt-4o"))
    db_session.add(_usage_event(org_id, model_name="gpt-3.5"))
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    models = resp.json()["llm_metrics"]["top_models"]
    assert models[0]["model_name"] == "gpt-4o"
    assert models[0]["event_count"] == 3
    assert models[1]["model_name"] == "gpt-3.5"


# ---------------------------------------------------------------------------
# I. indexing_metrics from pipeline usage events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_indexing_metrics_total_jobs(
    obs_client: AsyncClient, db_session: AsyncSession
) -> None:
    from uuid import UUID

    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])
    db_session.add(
        _usage_event(
            org_id, event_type="pipeline.index", model_name=None, metadata={"status": "completed"}
        )
    )
    db_session.add(
        _usage_event(
            org_id, event_type="pipeline.index", model_name=None, metadata={"status": "failed"}
        )
    )
    db_session.add(_usage_event(org_id, event_type="chat.answer", model_name="gpt-4o", metadata={}))
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    idx = resp.json()["indexing_metrics"]
    assert idx["total_jobs"] == 2
    assert idx["succeeded_jobs"] == 1
    assert idx["failed_jobs"] == 1


# ---------------------------------------------------------------------------
# J. indexing success_rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_indexing_success_rate(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    from uuid import UUID

    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])
    for _ in range(4):
        db_session.add(
            _usage_event(
                org_id, event_type="pipeline.run", model_name=None, metadata={"status": "completed"}
            )
        )
    db_session.add(
        _usage_event(
            org_id, event_type="pipeline.run", model_name=None, metadata={"status": "failed"}
        )
    )
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    idx = resp.json()["indexing_metrics"]
    assert abs(idx["success_rate"] - 4 / 5) < 1e-6


# ---------------------------------------------------------------------------
# K. storage_metrics counts documents by status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_metrics(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    from uuid import UUID

    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])
    user_id = UUID(ctx["user_id"])
    db_session.add(_document(org_id, user_id, status="indexed", chunk_count=10))
    db_session.add(_document(org_id, user_id, status="indexed", chunk_count=5))
    db_session.add(_document(org_id, user_id, status="failed"))
    db_session.add(_document(org_id, user_id, status="processing"))
    db_session.add(_document(org_id, user_id, status="deleted"))
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    storage = resp.json()["storage_metrics"]
    assert storage["total_documents"] == 4
    assert storage["indexed_documents"] == 2
    assert storage["failed_documents"] == 1
    assert storage["pending_documents"] == 1
    assert storage["total_chunks"] == 15


# ---------------------------------------------------------------------------
# L. Date range filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_date_range_filters_audit_logs(
    obs_client: AsyncClient, db_session: AsyncSession
) -> None:
    from uuid import UUID

    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])

    old_log = _audit_log(org_id, result="success")
    old_log.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    db_session.add(old_log)

    recent_log = _audit_log(org_id, result="success")
    db_session.add(recent_log)
    await db_session.flush()

    today = _now().date().isoformat()
    resp = await obs_client.get(
        f"/api/admin/observability?from={today}&to={today}",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["api_metrics"]["total_requests"] == 1


# ---------------------------------------------------------------------------
# M. from > to returns 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_date_range_returns_400(
    obs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await obs_client.get(
        "/api/admin/observability?from=2026-06-10&to=2026-06-01",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# N. Org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_isolation(obs_client: AsyncClient, db_session: AsyncSession) -> None:
    from uuid import UUID

    ctx_a = await _make_org_user(db_session)
    ctx_b = await _make_org_user(db_session)
    org_b_id = UUID(ctx_b["org_id"])

    db_session.add(_audit_log(org_b_id, result="failed"))
    await db_session.flush()

    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx_a["token"]))
    assert resp.json()["api_metrics"]["total_requests"] == 0


# ---------------------------------------------------------------------------
# O. Response shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_includes_metadata(
    obs_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await obs_client.get("/api/admin/observability", headers=_auth(ctx["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["organization_id"] == ctx["org_id"]
    assert "generated_at" in data
    assert "range" in data
    assert "from" in data["range"]
    assert "to" in data["range"]
