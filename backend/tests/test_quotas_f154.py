"""Backend tests for F154: Quotas and rate-limit management.

Covers:
  A. GET /admin/quotas/policy — 404 when no policy exists
  B. PATCH /admin/quotas/policy — create policy and read back
  C. PATCH /admin/quotas/policy — partial update merges quota types
  D. DELETE /admin/quotas/policy — resets org to system defaults
  E. GET /admin/quotas/usage — returns dashboard for all quota types
  F. GET /admin/quotas/usage — reflects incremented usage counters
  G. GET /admin/quotas/change-log — change log recorded on every update
  H. Role guards — member/viewer cannot mutate policy or overrides
  I. Org isolation — policy for one org not visible to another
  J. POST /admin/quotas/overrides — create org-wide override (owner only)
  K. POST /admin/quotas/overrides — create per-user override
  L. GET /admin/quotas/overrides — list overrides with pagination
  M. DELETE /admin/quotas/overrides/{id} — remove override (owner only)
  N. Soft/hard limit validation — soft > hard rejected
  O. Invalid quota_type rejected on override creation
  P. near_limit flag set at 80% of hard limit
  Q. over_hard_limit flag set when current exceeds hard limit
  R. GET /quotas/my-usage — any role can fetch org quota status
  S. Override creation requires owner role (admin forbidden)
  T. Reset to defaults — policy 404 after delete

Run:
    pytest tests/test_quotas_f154.py -v
"""

from __future__ import annotations

import os
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
from app.domains.quota.schemas.quota_schemas import QuotaType
from app.domains.quota.services.quota_service import increment_quota_usage
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def quota_client(
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
async def admin_ctx(db_session: AsyncSession) -> dict:
    org = Organization(name="Quota Test Org", slug=f"quota-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"admin-{uuid4().hex[:6]}@test.com", display_name="Admin")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id, user_id=user.id, role=OrganizationRole.admin.value
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.admin.value)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


@pytest_asyncio.fixture
async def owner_ctx(db_session: AsyncSession) -> dict:
    org = Organization(name="Quota Owner Org", slug=f"quota-owner-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"owner-{uuid4().hex[:6]}@test.com", display_name="Owner")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id, user_id=user.id, role=OrganizationRole.owner.value
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.owner.value)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


@pytest_asyncio.fixture
async def member_ctx(db_session: AsyncSession) -> dict:
    org = Organization(name="Quota Member Org", slug=f"quota-member-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"member-{uuid4().hex[:6]}@test.com", display_name="Member")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id, user_id=user.id, role=OrganizationRole.member.value
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.member.value)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


# ---------------------------------------------------------------------------
# A. GET — 404 when no policy configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_policy_not_found(quota_client: AsyncClient, admin_ctx: dict) -> None:
    resp = await quota_client.get(
        "/api/admin/quotas/policy",
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# B. PATCH — create policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_policy(quota_client: AsyncClient, admin_ctx: dict) -> None:
    resp = await quota_client.patch(
        "/api/admin/quotas/policy",
        json={
            "uploads": {"soft_limit": 50, "hard_limit": 100, "reset_window": "per_day"},
            "questions": {"soft_limit": 500, "hard_limit": 1000, "reset_window": "per_day"},
            "change_note": "Initial quota config",
        },
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["organization_id"] == admin_ctx["org_id"]
    assert data["version"] == 1
    assert data["limits"]["uploads"]["soft_limit"] == 50
    assert data["limits"]["uploads"]["hard_limit"] == 100
    assert data["limits"]["questions"]["hard_limit"] == 1000


# ---------------------------------------------------------------------------
# C. PATCH — partial update merges quota types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_update_merges(quota_client: AsyncClient, admin_ctx: dict) -> None:
    # Create initial
    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"uploads": {"soft_limit": 50, "hard_limit": 100, "reset_window": "per_day"}},
        headers=_auth(admin_ctx["token"]),
    )
    # Partial update — only tokens
    resp = await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"tokens": {"soft_limit": 100000, "hard_limit": 500000, "reset_window": "per_month"}},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # uploads should still be present
    assert data["limits"]["uploads"]["hard_limit"] == 100
    # tokens now set
    assert data["limits"]["tokens"]["hard_limit"] == 500000
    assert data["version"] == 2


# ---------------------------------------------------------------------------
# D. DELETE — reset to system defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_policy(quota_client: AsyncClient, admin_ctx: dict) -> None:
    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"uploads": {"soft_limit": 10, "hard_limit": 20, "reset_window": "per_day"}},
        headers=_auth(admin_ctx["token"]),
    )
    resp = await quota_client.delete(
        "/api/admin/quotas/policy",
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# E. GET /usage — all quota types returned with zeroes when no usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_dashboard_empty(quota_client: AsyncClient, admin_ctx: dict) -> None:
    resp = await quota_client.get(
        "/api/admin/quotas/usage",
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["organization_id"] == admin_ctx["org_id"]
    assert len(data["quota_usage"]) == 9  # one per QuotaType
    for item in data["quota_usage"]:
        # seats is computed live from member count (1 member in fixture), others are counters starting at 0
        if item["quota_type"] == "seats":
            assert item["current_value"] == 1
        else:
            assert item["current_value"] == 0
        assert item["over_hard_limit"] is False


# ---------------------------------------------------------------------------
# F. GET /usage — reflects incremented usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_dashboard_reflects_increments(
    quota_client: AsyncClient, admin_ctx: dict, db_session: AsyncSession
) -> None:
    from uuid import UUID

    org_id = UUID(admin_ctx["org_id"])

    # Set a hard limit
    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"uploads": {"soft_limit": 5, "hard_limit": 10, "reset_window": "per_day"}},
        headers=_auth(admin_ctx["token"]),
    )
    # Increment usage directly via service
    await increment_quota_usage(
        db_session, organization_id=org_id, quota_type=QuotaType.uploads, amount=4
    )
    await db_session.commit()

    resp = await quota_client.get(
        "/api/admin/quotas/usage",
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    uploads = next(i for i in data["quota_usage"] if i["quota_type"] == "uploads")
    assert uploads["current_value"] == 4
    assert uploads["soft_limit"] == 5
    assert uploads["hard_limit"] == 10
    assert uploads["near_limit"] is False  # 4/10 = 40%, below 80% hard limit threshold
    assert uploads["over_soft_limit"] is False
    assert uploads["over_hard_limit"] is False


# ---------------------------------------------------------------------------
# G. Change log recorded on every update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_log_recorded(quota_client: AsyncClient, admin_ctx: dict) -> None:
    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={
            "uploads": {"soft_limit": 10, "hard_limit": 20, "reset_window": "per_day"},
            "change_note": "First",
        },
        headers=_auth(admin_ctx["token"]),
    )
    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={
            "questions": {"soft_limit": 100, "hard_limit": 200, "reset_window": "per_day"},
            "change_note": "Second",
        },
        headers=_auth(admin_ctx["token"]),
    )
    resp = await quota_client.get(
        "/api/admin/quotas/change-log",
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 2
    assert data["items"][0]["version_number"] == 2
    assert data["items"][0]["change_note"] == "Second"


# ---------------------------------------------------------------------------
# H. Role guards — member/viewer cannot mutate policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_cannot_patch_policy(quota_client: AsyncClient, member_ctx: dict) -> None:
    resp = await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"uploads": {"soft_limit": 10, "hard_limit": 20, "reset_window": "per_day"}},
        headers=_auth(member_ctx["token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_delete_policy(quota_client: AsyncClient, member_ctx: dict) -> None:
    resp = await quota_client.delete(
        "/api/admin/quotas/policy",
        headers=_auth(member_ctx["token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_get_policy(quota_client: AsyncClient, member_ctx: dict) -> None:
    resp = await quota_client.get(
        "/api/admin/quotas/policy",
        headers=_auth(member_ctx["token"]),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# I. Org isolation — one org cannot see another's policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_isolation(quota_client: AsyncClient, db_session: AsyncSession) -> None:
    # Org A sets a policy
    org_a = Organization(name="Org A", slug=f"org-a-{uuid4().hex[:8]}")
    db_session.add(org_a)
    await db_session.flush()
    user_a = User(email=f"ua-{uuid4().hex[:6]}@test.com", display_name="UA")
    db_session.add(user_a)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org_a.id, user_id=user_a.id, role=OrganizationRole.admin.value
        )
    )
    await db_session.flush()
    token_a = _make_token(str(user_a.id), str(org_a.id), OrganizationRole.admin.value)

    # Org B (no policy)
    org_b = Organization(name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    db_session.add(org_b)
    await db_session.flush()
    user_b = User(email=f"ub-{uuid4().hex[:6]}@test.com", display_name="UB")
    db_session.add(user_b)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org_b.id, user_id=user_b.id, role=OrganizationRole.admin.value
        )
    )
    await db_session.flush()
    token_b = _make_token(str(user_b.id), str(org_b.id), OrganizationRole.admin.value)

    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"uploads": {"soft_limit": 99, "hard_limit": 999, "reset_window": "per_day"}},
        headers=_auth(token_a),
    )

    # Org B should get 404
    resp = await quota_client.get("/api/admin/quotas/policy", headers=_auth(token_b))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# J. Create org-wide override (owner only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_orgwide_override(quota_client: AsyncClient, owner_ctx: dict) -> None:
    resp = await quota_client.post(
        "/api/admin/quotas/overrides",
        json={
            "quota_type": "uploads",
            "hard_limit_override": 500,
            "reason": "Promotional campaign",
        },
        headers=_auth(owner_ctx["token"]),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["quota_type"] == "uploads"
    assert data["hard_limit_override"] == 500
    assert data["target_user_id"] is None
    assert data["reason"] == "Promotional campaign"


# ---------------------------------------------------------------------------
# K. Create per-user override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_peruser_override(
    quota_client: AsyncClient, owner_ctx: dict, db_session: AsyncSession
) -> None:
    target_user = User(email=f"target-{uuid4().hex[:6]}@test.com", display_name="Target")
    db_session.add(target_user)
    await db_session.flush()

    resp = await quota_client.post(
        "/api/admin/quotas/overrides",
        json={
            "quota_type": "questions",
            "target_user_id": str(target_user.id),
            "hard_limit_override": 2000,
            "reason": "Power user",
        },
        headers=_auth(owner_ctx["token"]),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["target_user_id"] == str(target_user.id)
    assert data["hard_limit_override"] == 2000


# ---------------------------------------------------------------------------
# L. List overrides with pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_overrides(quota_client: AsyncClient, owner_ctx: dict) -> None:
    for i in range(3):
        await quota_client.post(
            "/api/admin/quotas/overrides",
            json={
                "quota_type": "uploads",
                "hard_limit_override": 100 * (i + 1),
                "reason": f"Override {i}",
            },
            headers=_auth(owner_ctx["token"]),
        )

    resp = await quota_client.get(
        "/api/admin/quotas/overrides?limit=2&offset=0",
        headers=_auth(owner_ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# M. Delete override (owner only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_override(quota_client: AsyncClient, owner_ctx: dict) -> None:
    create_resp = await quota_client.post(
        "/api/admin/quotas/overrides",
        json={"quota_type": "tokens", "hard_limit_override": 1000000, "reason": "To be deleted"},
        headers=_auth(owner_ctx["token"]),
    )
    assert create_resp.status_code == 201
    override_id = create_resp.json()["override_id"]

    del_resp = await quota_client.delete(
        f"/api/admin/quotas/overrides/{override_id}",
        headers=_auth(owner_ctx["token"]),
    )
    assert del_resp.status_code == 204

    list_resp = await quota_client.get(
        "/api/admin/quotas/overrides",
        headers=_auth(owner_ctx["token"]),
    )
    assert list_resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# N. Soft/hard validation — soft > hard rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_greater_than_hard_rejected(quota_client: AsyncClient, admin_ctx: dict) -> None:
    resp = await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"uploads": {"soft_limit": 200, "hard_limit": 100, "reset_window": "per_day"}},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# O. Invalid quota_type rejected on override creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_quota_type_override(quota_client: AsyncClient, owner_ctx: dict) -> None:
    resp = await quota_client.post(
        "/api/admin/quotas/overrides",
        json={"quota_type": "nonexistent", "hard_limit_override": 100, "reason": "Test"},
        headers=_auth(owner_ctx["token"]),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# P. near_limit flag at 80% of hard limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_near_limit_flag(
    quota_client: AsyncClient, admin_ctx: dict, db_session: AsyncSession
) -> None:
    from uuid import UUID

    org_id = UUID(admin_ctx["org_id"])

    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"evaluations": {"soft_limit": None, "hard_limit": 10, "reset_window": "per_day"}},
        headers=_auth(admin_ctx["token"]),
    )
    # 8 out of 10 = 80% — exactly at threshold
    await increment_quota_usage(
        db_session, organization_id=org_id, quota_type=QuotaType.evaluations, amount=8
    )
    await db_session.commit()

    resp = await quota_client.get("/api/admin/quotas/usage", headers=_auth(admin_ctx["token"]))
    data = resp.json()
    evals = next(i for i in data["quota_usage"] if i["quota_type"] == "evaluations")
    assert evals["near_limit"] is True
    assert evals["over_hard_limit"] is False


# ---------------------------------------------------------------------------
# Q. over_hard_limit flag when current exceeds limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_hard_limit_flag(
    quota_client: AsyncClient, admin_ctx: dict, db_session: AsyncSession
) -> None:
    from uuid import UUID

    org_id = UUID(admin_ctx["org_id"])

    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"agent_runs": {"soft_limit": 5, "hard_limit": 10, "reset_window": "per_day"}},
        headers=_auth(admin_ctx["token"]),
    )
    await increment_quota_usage(
        db_session, organization_id=org_id, quota_type=QuotaType.agent_runs, amount=11
    )
    await db_session.commit()

    resp = await quota_client.get("/api/admin/quotas/usage", headers=_auth(admin_ctx["token"]))
    data = resp.json()
    assert data["has_overages"] is True
    agent_runs = next(i for i in data["quota_usage"] if i["quota_type"] == "agent_runs")
    assert agent_runs["over_hard_limit"] is True
    assert agent_runs["over_soft_limit"] is True


# ---------------------------------------------------------------------------
# R. GET /quotas/my-usage — any role can access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_usage_any_role(quota_client: AsyncClient, member_ctx: dict) -> None:
    resp = await quota_client.get(
        "/api/quotas/my-usage",
        headers=_auth(member_ctx["token"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["organization_id"] == member_ctx["org_id"]
    assert len(data["quota_usage"]) == 9


# ---------------------------------------------------------------------------
# S. Override creation requires owner (admin forbidden)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_cannot_create_override(quota_client: AsyncClient, admin_ctx: dict) -> None:
    resp = await quota_client.post(
        "/api/admin/quotas/overrides",
        json={"quota_type": "uploads", "hard_limit_override": 500, "reason": "Test"},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# T. Reset to defaults — 404 after delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_404_after_reset(quota_client: AsyncClient, admin_ctx: dict) -> None:
    await quota_client.patch(
        "/api/admin/quotas/policy",
        json={"uploads": {"soft_limit": 10, "hard_limit": 20, "reset_window": "per_day"}},
        headers=_auth(admin_ctx["token"]),
    )
    await quota_client.delete("/api/admin/quotas/policy", headers=_auth(admin_ctx["token"]))
    resp = await quota_client.get("/api/admin/quotas/policy", headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 404
