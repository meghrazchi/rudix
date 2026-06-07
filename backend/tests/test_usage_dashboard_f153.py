"""Backend tests for F153: Usage and cost dashboard.

Covers:
  A. GET /admin/usage/dashboard — 200 with totals for admin
  B. GET /admin/usage/dashboard — 403 for member
  C. GET /admin/usage/dashboard — empty org returns zero totals
  D. GET /admin/usage/dashboard — date range filter excludes out-of-range events
  E. GET /admin/usage/dashboard — model filter narrows results
  F. GET /admin/usage/dashboard — feature_area filter narrows to agent events
  G. GET /admin/usage/dashboard — top_users table populated and sorted by cost
  H. GET /admin/usage/dashboard — top_models table populated and sorted by cost
  I. GET /admin/usage/dashboard — is_cost_estimate always true
  J. GET /admin/usage/export — 200 CSV for admin
  K. GET /admin/usage/export — 200 JSON for admin

Run:
    pytest tests/test_usage_dashboard_f153.py -v
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
async def dash_client(
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


@pytest_asyncio.fixture
async def admin_ctx(db_session: AsyncSession):
    org = Organization(name=f"Dash Org {uuid4().hex[:6]}", slug=f"dash-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"admin-{uuid4().hex[:6]}@test.com", display_name="Admin")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.admin.value,
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id))
    return {"org": org, "user": user, "token": token}


async def _seed_event(
    db_session: AsyncSession,
    *,
    org_id,
    user_id=None,
    event_type: str = "chat.question",
    model_name: str | None = "gpt-4o",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost_usd: Decimal | None = Decimal("0.01"),
    created_at: datetime | None = None,
) -> UsageEvent:
    event = UsageEvent(
        organization_id=org_id,
        user_id=user_id,
        event_type=event_type,
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        metadata_json={},
    )
    if created_at is not None:
        event.created_at = created_at
    db_session.add(event)
    await db_session.flush()
    return event


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_returns_totals_for_admin(dash_client, admin_ctx, db_session):
    """A: admin gets 200 with correct totals."""
    ctx = admin_ctx
    await _seed_event(
        db_session,
        org_id=ctx["org"].id,
        user_id=ctx["user"].id,
        input_tokens=200,
        output_tokens=80,
        cost_usd=Decimal("0.05"),
    )

    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(ctx["token"]),
        params={"from": "2020-01-01", "to": "2099-12-31"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["input_tokens"] == 200
    assert data["totals"]["output_tokens"] == 80
    assert float(data["totals"]["estimated_cost_usd"]) == pytest.approx(0.05, abs=1e-4)
    assert data["totals"]["active_users"] == 1
    assert data["is_cost_estimate"] is True


@pytest.mark.asyncio
async def test_dashboard_forbidden_for_member(dash_client, db_session):
    """B: member role receives 403."""
    org = Organization(name=f"Org {uuid4().hex}", slug=f"org-m-{uuid4().hex[:8]}")
    db_session.add(org)
    user = User(email=f"m-{uuid4().hex[:6]}@test.com", display_name="Member")
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.member.value)
    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_empty_org_returns_zeros(dash_client, admin_ctx, db_session):
    """C: org with no events returns zero totals."""
    ctx = admin_ctx
    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(ctx["token"]),
        params={"from": "2020-01-01", "to": "2099-12-31"},
    )
    assert resp.status_code == 200
    data = resp.json()
    totals = data["totals"]
    assert totals["questions_asked"] == 0
    assert totals["input_tokens"] == 0
    assert totals["active_users"] == 0
    assert totals["agent_runs"] == 0
    assert data["series"] == []
    assert data["top_users"] == []
    assert data["top_models"] == []


@pytest.mark.asyncio
async def test_dashboard_date_range_filter(dash_client, admin_ctx, db_session):
    """D: events outside the date range are excluded."""
    ctx = admin_ctx
    old_ts = datetime(2022, 1, 1, tzinfo=UTC)
    recent_ts = datetime(2099, 6, 1, tzinfo=UTC)
    await _seed_event(
        db_session,
        org_id=ctx["org"].id,
        input_tokens=500,
        created_at=old_ts,
    )
    await _seed_event(
        db_session,
        org_id=ctx["org"].id,
        input_tokens=10,
        created_at=recent_ts,
    )

    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(ctx["token"]),
        params={"from": "2099-01-01", "to": "2099-12-31"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["input_tokens"] == 10


@pytest.mark.asyncio
async def test_dashboard_model_filter(dash_client, admin_ctx, db_session):
    """E: model filter returns only events for that model."""
    ctx = admin_ctx
    await _seed_event(db_session, org_id=ctx["org"].id, model_name="gpt-4o", input_tokens=100)
    await _seed_event(
        db_session, org_id=ctx["org"].id, model_name="claude-3-sonnet", input_tokens=200
    )

    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(ctx["token"]),
        params={"from": "2020-01-01", "to": "2099-12-31", "model": "claude-3-sonnet"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["input_tokens"] == 200


@pytest.mark.asyncio
async def test_dashboard_feature_area_filter(dash_client, admin_ctx, db_session):
    """F: feature_area=agent returns only agent.* events."""
    ctx = admin_ctx
    await _seed_event(
        db_session,
        org_id=ctx["org"].id,
        event_type="agent.runtime",
        input_tokens=300,
    )
    await _seed_event(
        db_session,
        org_id=ctx["org"].id,
        event_type="chat.question",
        input_tokens=100,
    )

    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(ctx["token"]),
        params={"from": "2020-01-01", "to": "2099-12-31", "feature_area": "agent"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totals"]["input_tokens"] == 300


@pytest.mark.asyncio
async def test_dashboard_top_users_populated_and_sorted(dash_client, admin_ctx, db_session):
    """G: top_users lists users by cost descending."""
    ctx = admin_ctx
    org_id = ctx["org"].id

    user2 = User(email=f"u2-{uuid4().hex[:6]}@test.com", display_name="U2")
    db_session.add(user2)
    await db_session.flush()

    await _seed_event(
        db_session,
        org_id=org_id,
        user_id=ctx["user"].id,
        cost_usd=Decimal("1.00"),
    )
    await _seed_event(
        db_session,
        org_id=org_id,
        user_id=user2.id,
        cost_usd=Decimal("5.00"),
    )

    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(ctx["token"]),
        params={"from": "2020-01-01", "to": "2099-12-31"},
    )
    assert resp.status_code == 200
    top_users = resp.json()["top_users"]
    assert len(top_users) == 2
    costs = [u["estimated_cost_usd"] for u in top_users]
    assert costs == sorted(costs, reverse=True)


@pytest.mark.asyncio
async def test_dashboard_top_models_populated_and_sorted(dash_client, admin_ctx, db_session):
    """H: top_models lists models by cost descending."""
    ctx = admin_ctx
    org_id = ctx["org"].id

    await _seed_event(db_session, org_id=org_id, model_name="gpt-4o", cost_usd=Decimal("2.00"))
    await _seed_event(
        db_session, org_id=org_id, model_name="claude-3-sonnet", cost_usd=Decimal("10.00")
    )

    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(ctx["token"]),
        params={"from": "2020-01-01", "to": "2099-12-31"},
    )
    assert resp.status_code == 200
    top_models = resp.json()["top_models"]
    assert len(top_models) == 2
    costs = [m["estimated_cost_usd"] for m in top_models]
    assert costs == sorted(costs, reverse=True)
    model_names = {m["model_name"] for m in top_models}
    assert "gpt-4o" in model_names
    assert "claude-3-sonnet" in model_names


@pytest.mark.asyncio
async def test_dashboard_is_cost_estimate_always_true(dash_client, admin_ctx, db_session):
    """I: is_cost_estimate is always true in response."""
    ctx = admin_ctx
    resp = await dash_client.get(
        "/admin/usage/dashboard",
        headers=_auth(ctx["token"]),
        params={"from": "2020-01-01", "to": "2099-12-31"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_cost_estimate"] is True


@pytest.mark.asyncio
async def test_export_csv_for_admin(dash_client, admin_ctx, db_session):
    """J: admin can export usage as CSV."""
    ctx = admin_ctx
    await _seed_event(
        db_session,
        org_id=ctx["org"].id,
        user_id=ctx["user"].id,
        event_type="chat.question",
        input_tokens=50,
        cost_usd=Decimal("0.002"),
    )

    resp = await dash_client.get(
        "/admin/usage/export",
        headers=_auth(ctx["token"]),
        params={"format": "csv", "from": "2020-01-01", "to": "2099-12-31"},
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    body = resp.text
    assert "event_type" in body
    assert "chat.question" in body
    assert "estimated_cost_usd" in body


@pytest.mark.asyncio
async def test_export_json_for_admin(dash_client, admin_ctx, db_session):
    """K: admin can export usage as JSON."""
    ctx = admin_ctx
    await _seed_event(
        db_session,
        org_id=ctx["org"].id,
        event_type="agent.runtime",
        model_name="gpt-4o",
        input_tokens=80,
        cost_usd=Decimal("0.004"),
    )

    resp = await dash_client.get(
        "/admin/usage/export",
        headers=_auth(ctx["token"]),
        params={"format": "json", "from": "2020-01-01", "to": "2099-12-31"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_cost_estimate"] is True
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["event_type"] == "agent.runtime"
    assert item["model_name"] == "gpt-4o"
    assert item["input_tokens"] == 80
