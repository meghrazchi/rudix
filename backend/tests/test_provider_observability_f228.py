"""Backend tests for F228: LLM provider observability, usage, cost, and health monitoring.

Covers:
  A. GET /admin/provider-observability — empty org returns telemetry_missing=True
  B. GET /admin/provider-observability — role guard: member/viewer get 403
  C. GET /admin/provider-observability — single provider card returned
  D. GET /admin/provider-observability — failure_rate computed from error_code
  E. GET /admin/provider-observability — timeout_rate from timed_out=True events
  F. GET /admin/provider-observability — fallback_rate from fallback_used=True events
  G. GET /admin/provider-observability — retry_rate and avg_retry_count computed
  H. GET /admin/provider-observability — avg_latency_ms from metadata latency_ms
  I. GET /admin/provider-observability — p95_latency_ms computed correctly
  J. GET /admin/provider-observability — multiple providers returned as separate cards
  K. GET /admin/provider-observability — from/to date range filters events
  L. GET /admin/provider-observability — from > to returns 400
  M. GET /admin/provider-observability — org isolation: other-org events excluded
  N. GET /admin/provider-observability — slo_suggestions emitted when failure_rate > 5%
  O. GET /admin/provider-observability — events without provider_key excluded

Run:
    pytest tests/test_provider_observability_f228.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
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
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import UsageEvent
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def po_client(
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
    slug = f"po-org-{uuid4().hex[:8]}"
    org = Organization(name=f"PO Org {slug}", slug=slug)
    db.add(org)
    await db.flush()

    user = User(email=f"po-{uuid4().hex[:6]}@test.com", display_name="PO User")
    db.add(user)
    await db.flush()

    member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    db.add(member)
    await db.flush()

    token = _make_token(str(user.id), str(org.id), role)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _provider_event(
    org_id,
    *,
    provider_key: str = "openai",
    error_code: str | None = None,
    timed_out: bool = False,
    fallback_used: bool = False,
    retry_count: int | None = None,
    latency_ms: float | None = None,
    created_at: datetime | None = None,
) -> UsageEvent:
    metadata: dict = {}
    if latency_ms is not None:
        metadata["latency_ms"] = latency_ms
    event = UsageEvent(
        organization_id=org_id,
        event_type="chat.completion",
        model_name="gpt-4o",
        input_tokens=10,
        output_tokens=20,
        cost_usd=Decimal("0.001"),
        metadata_json=metadata,
        provider_key=provider_key,
        task_type="chat",
        error_code=error_code,
        timed_out=timed_out,
        fallback_used=fallback_used,
        retry_count=retry_count,
    )
    if created_at is not None:
        event.created_at = created_at
    return event


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_empty_org_returns_telemetry_missing(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["telemetry_missing"] is True
    assert data["providers"] == []


@pytest.mark.asyncio
async def test_b_role_guard_member_viewer_get_403(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    for role in (OrganizationRole.member.value, OrganizationRole.viewer.value):
        ctx = await _make_org_user(db_session, role=role)
        await db_session.commit()
        resp = await po_client.get(
            "/api/v1/admin/provider-observability",
            headers=_auth(ctx["token"]),
        )
        assert resp.status_code == 403, f"Expected 403 for role={role}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_c_single_provider_card_returned(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_provider_event(org_id, provider_key="openai"))
    db_session.add(_provider_event(org_id, provider_key="openai"))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["telemetry_missing"] is False
    assert len(data["providers"]) == 1
    card = data["providers"][0]
    assert card["provider_key"] == "openai"
    assert card["total_events"] == 2


@pytest.mark.asyncio
async def test_d_failure_rate_from_error_code(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    # 2 successes, 1 failure
    db_session.add(_provider_event(org_id))
    db_session.add(_provider_event(org_id))
    db_session.add(_provider_event(org_id, error_code="provider_error"))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    card = resp.json()["providers"][0]
    assert card["failed_events"] == 1
    assert abs(card["failure_rate"] - 1 / 3) < 1e-6


@pytest.mark.asyncio
async def test_e_timeout_rate_from_timed_out_flag(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_provider_event(org_id, timed_out=True))
    db_session.add(_provider_event(org_id, timed_out=False))
    db_session.add(_provider_event(org_id, timed_out=False))
    db_session.add(_provider_event(org_id, timed_out=False))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    card = resp.json()["providers"][0]
    assert card["timed_out_events"] == 1
    assert abs(card["timeout_rate"] - 0.25) < 1e-6


@pytest.mark.asyncio
async def test_f_fallback_rate_from_fallback_used(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_provider_event(org_id, fallback_used=True))
    db_session.add(_provider_event(org_id, fallback_used=True))
    db_session.add(_provider_event(org_id, fallback_used=False))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    card = resp.json()["providers"][0]
    assert card["fallback_events"] == 2
    assert abs(card["fallback_rate"] - 2 / 3) < 1e-6


@pytest.mark.asyncio
async def test_g_retry_rate_and_avg_retry_count(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_provider_event(org_id, retry_count=2))
    db_session.add(_provider_event(org_id, retry_count=4))
    db_session.add(_provider_event(org_id, retry_count=0))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    card = resp.json()["providers"][0]
    # retry_events counts only events with retry_count > 0
    assert card["retry_events"] == 2
    assert abs(card["retry_rate"] - 2 / 3) < 1e-6
    # avg_retry_count = (2 + 4) / 2
    assert abs(card["avg_retry_count"] - 3.0) < 1e-6


@pytest.mark.asyncio
async def test_h_avg_latency_from_metadata(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_provider_event(org_id, latency_ms=100.0))
    db_session.add(_provider_event(org_id, latency_ms=300.0))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    card = resp.json()["providers"][0]
    assert abs(card["avg_latency_ms"] - 200.0) < 1e-3


@pytest.mark.asyncio
async def test_i_p95_latency_computed_correctly(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    # 20 events with latencies 100, 200, ..., 2000 ms
    for i in range(1, 21):
        db_session.add(_provider_event(org_id, latency_ms=float(i * 100)))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    card = resp.json()["providers"][0]
    # P95 of 100..2000 (20 values) = index 18.05 → ~1905
    assert card["p95_latency_ms"] is not None
    assert 1800 <= card["p95_latency_ms"] <= 2000


@pytest.mark.asyncio
async def test_j_multiple_providers_separate_cards(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_provider_event(org_id, provider_key="openai"))
    db_session.add(_provider_event(org_id, provider_key="openai"))
    db_session.add(_provider_event(org_id, provider_key="local"))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    assert len(providers) == 2
    keys = {p["provider_key"] for p in providers}
    assert keys == {"openai", "local"}
    openai_card = next(p for p in providers if p["provider_key"] == "openai")
    assert openai_card["total_events"] == 2


@pytest.mark.asyncio
async def test_k_date_range_filters_events(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    old = _provider_event(org_id)
    old.created_at = _now() - timedelta(days=60)
    recent = _provider_event(org_id)
    recent.created_at = _now() - timedelta(days=5)
    db_session.add(old)
    db_session.add(recent)
    await db_session.commit()

    today = _now().date()
    from_date = (today - timedelta(days=14)).isoformat()
    to_date = today.isoformat()

    resp = await po_client.get(
        f"/api/v1/admin/provider-observability?from={from_date}&to={to_date}",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["providers"]) == 1
    assert data["providers"][0]["total_events"] == 1


@pytest.mark.asyncio
async def test_l_from_greater_than_to_returns_400(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability?from=2026-06-10&to=2026-06-01",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_m_org_isolation_excludes_other_org_events(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx_a = await _make_org_user(db_session)
    ctx_b = await _make_org_user(db_session)

    db_session.add(_provider_event(ctx_b["org_id"], provider_key="openai"))
    await db_session.commit()

    # Org A should see no data
    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx_a["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["telemetry_missing"] is True


@pytest.mark.asyncio
async def test_n_slo_suggestions_emitted_when_failure_rate_high(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    # 6 failures out of 10 = 60% failure rate → exceeds 5% threshold
    for _ in range(6):
        db_session.add(_provider_event(org_id, error_code="provider_error"))
    for _ in range(4):
        db_session.add(_provider_event(org_id))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    card = resp.json()["providers"][0]
    slo = card["slo_suggestions"]
    assert len(slo) >= 1
    metrics = {s["metric"] for s in slo}
    assert "failure_rate" in metrics


@pytest.mark.asyncio
async def test_o_events_without_provider_key_excluded(
    po_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    # Legacy event without provider_key
    legacy = UsageEvent(
        organization_id=org_id,
        event_type="chat.completion",
        model_name="gpt-4o",
        input_tokens=10,
        output_tokens=20,
        cost_usd=Decimal("0.001"),
        metadata_json={},
    )
    db_session.add(legacy)
    # Modern event with provider_key
    db_session.add(_provider_event(org_id, provider_key="openai"))
    await db_session.commit()

    resp = await po_client.get(
        "/api/v1/admin/provider-observability",
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only the modern event should appear
    assert data["telemetry_missing"] is False
    assert len(data["providers"]) == 1
    assert data["providers"][0]["total_events"] == 1
