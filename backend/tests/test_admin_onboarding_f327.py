"""Admin onboarding config and sample dataset tests (F327)."""

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
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def admin_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_principal(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    sample_docs_enabled: bool = False,
) -> tuple[User, Organization]:
    org = Organization(
        name=f"Org-{uuid4().hex[:8]}",
        slug=f"org-{uuid4().hex[:8]}",
        sample_docs_enabled=sample_docs_enabled,
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value)
    )
    await db_session.commit()
    return user, org


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


# ── GET /admin/onboarding/config ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_onboarding_config_defaults(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    resp = await admin_client.get(
        "/admin/onboarding/config",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sample_docs_enabled"] is False
    assert data["reset_at"] is None


@pytest.mark.asyncio
async def test_get_onboarding_config_member_forbidden(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    resp = await admin_client.get(
        "/admin/onboarding/config",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 403


# ── PATCH /admin/onboarding/config ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_onboarding_config_enables_sample_docs(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.owner.value
    )
    resp = await admin_client.patch(
        "/admin/onboarding/config",
        json={"sample_docs_enabled": True},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sample_docs_enabled"] is True


@pytest.mark.asyncio
async def test_patch_onboarding_config_no_op_fields_preserved(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(
        db_session, role=OrganizationRole.admin, sample_docs_enabled=True
    )
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    resp = await admin_client.patch(
        "/admin/onboarding/config",
        json={},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    assert resp.json()["sample_docs_enabled"] is True


# ── POST /admin/onboarding/reset ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_onboarding_sets_reset_at(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.owner.value
    )
    resp = await admin_client.post(
        "/admin/onboarding/reset",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reset_at"] is not None


@pytest.mark.asyncio
async def test_reset_onboarding_member_forbidden(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    resp = await admin_client.post(
        "/admin/onboarding/reset",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reset_onboarding_is_idempotent(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    headers = _auth_headers(token=token, organization_id=str(org.id))
    r1 = await admin_client.post("/admin/onboarding/reset", headers=headers)
    r2 = await admin_client.post("/admin/onboarding/reset", headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    t1 = r1.json()["reset_at"]
    t2 = r2.json()["reset_at"]
    # Second reset updates the timestamp.
    assert t1 != t2


# ── POST /documents/sample ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_sample_dataset_success(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(
        db_session, role=OrganizationRole.owner, sample_docs_enabled=True
    )
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.owner.value
    )
    resp = await admin_client.post(
        "/documents/sample",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["created"] == 3
    assert data["skipped"] == 0
    assert len(data["document_ids"]) == 3


@pytest.mark.asyncio
async def test_load_sample_dataset_idempotent(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(
        db_session, role=OrganizationRole.owner, sample_docs_enabled=True
    )
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.owner.value
    )
    headers = _auth_headers(token=token, organization_id=str(org.id))
    r1 = await admin_client.post("/documents/sample", headers=headers)
    r2 = await admin_client.post("/documents/sample", headers=headers)
    assert r1.status_code == 201
    assert r2.status_code == 201
    d2 = r2.json()
    assert d2["created"] == 0
    assert d2["skipped"] == 3


@pytest.mark.asyncio
async def test_load_sample_dataset_disabled_403(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(
        db_session, role=OrganizationRole.owner, sample_docs_enabled=False
    )
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.owner.value
    )
    resp = await admin_client.post(
        "/documents/sample",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_load_sample_dataset_member_forbidden(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(
        db_session, role=OrganizationRole.member, sample_docs_enabled=True
    )
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    resp = await admin_client.post(
        "/documents/sample",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 403
