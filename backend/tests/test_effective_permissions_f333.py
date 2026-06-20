"""Tests for GET /auth/effective-permissions — F333."""

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
from app.auth.passwords import PasswordHashConfig, build_password_hasher, hash_password
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.custom_role import CustomRole, CustomRolePermission
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.permissions import ROLE_PERMISSIONS
from app.models.user import User

_password_hasher = build_password_hasher(
    PasswordHashConfig(
        memory_cost=65536,
        time_cost=3,
        parallelism=1,
        hash_length=32,
        salt_length=16,
    )
)

_ENDPOINT = "/api/v1/auth/effective-permissions"


@pytest_asyncio.fixture
async def auth_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
) -> tuple[User, Organization]:
    org = Organization(name="Test Org", slug=f"test-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Test User",
        hashed_password=hash_password("pw", _password_hasher),
        password_state="active",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, org


def _token(user: User, org: Organization, role: OrganizationRole) -> str:
    return create_app_access_token(
        subject=str(user.id),
        organization_id=str(org.id),
        role=role.value,
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(auth_client: AsyncClient) -> None:
    response = await auth_client.get(_ENDPOINT)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_owner_gets_full_permissions(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.owner)
    token = _token(user, org, OrganizationRole.owner)

    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "owner"
    assert data["custom_role_id"] is None
    expected = sorted(ROLE_PERMISSIONS["owner"])
    assert data["permissions"] == expected


@pytest.mark.asyncio
async def test_admin_permissions(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.admin)
    token = _token(user, org, OrganizationRole.admin)

    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "admin"
    assert "billing:manage" not in data["permissions"]
    assert "documents:manage" in data["permissions"]


@pytest.mark.asyncio
async def test_viewer_permissions(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.viewer)
    token = _token(user, org, OrganizationRole.viewer)

    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "viewer"
    assert "chat:use" in data["permissions"]
    assert "documents:delete" not in data["permissions"]
    assert "billing:manage" not in data["permissions"]


@pytest.mark.asyncio
async def test_member_permissions(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.member)
    token = _token(user, org, OrganizationRole.member)

    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "member"
    assert "documents:view" in data["permissions"]
    assert "documents:delete" not in data["permissions"]


@pytest.mark.asyncio
async def test_effective_permissions_endpoint_does_not_crash_for_custom_role_context(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.admin)

    custom_role = CustomRole(
        organization_id=org.id,
        name="Docs Reviewer",
        description="Read-only docs review role",
        base_role="member",
    )
    db_session.add(custom_role)
    await db_session.flush()
    db_session.add(
        CustomRolePermission(
            custom_role_id=custom_role.id,
            permission="documents:view",
        )
    )
    await db_session.flush()
    from sqlalchemy import select

    result = await db_session.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
        )
    )
    membership = result.scalar_one()
    membership.custom_role_id = custom_role.id
    await db_session.commit()

    token = _token(user, org, OrganizationRole.admin)
    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert data["custom_role_id"] == str(custom_role.id)
    assert "documents:view" in data["permissions"]


@pytest.mark.asyncio
async def test_billing_admin_permissions(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.billing_admin)
    token = _token(user, org, OrganizationRole.billing_admin)

    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert "billing:manage" in data["permissions"]
    assert "documents:view" not in data["permissions"]


@pytest.mark.asyncio
async def test_custom_role_with_extra_permission(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.viewer)

    custom_role = CustomRole(
        organization_id=org.id,
        name="Custom Viewer+",
        base_role="viewer",
    )
    db_session.add(custom_role)
    await db_session.flush()

    db_session.add(
        CustomRolePermission(
            custom_role_id=custom_role.id,
            permission="documents:upload",
        )
    )

    from sqlalchemy import select

    result = await db_session.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.user_id == user.id,
        )
    )
    membership = result.scalar_one()
    membership.custom_role_id = custom_role.id
    await db_session.commit()

    token = _token(user, org, OrganizationRole.viewer)
    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert data["custom_role_id"] == str(custom_role.id)
    assert "documents:upload" in data["permissions"]
    assert "chat:use" in data["permissions"]  # viewer base permissions also present


@pytest.mark.asyncio
async def test_permissions_are_sorted(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.admin)
    token = _token(user, org, OrganizationRole.admin)

    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    perms = response.json()["permissions"]
    assert perms == sorted(perms)


@pytest.mark.asyncio
async def test_security_admin_permissions(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_user(db_session, role=OrganizationRole.security_admin)
    token = _token(user, org, OrganizationRole.security_admin)

    response = await auth_client.get(_ENDPOINT, headers=_headers(token))

    assert response.status_code == 200
    data = response.json()
    assert "security_center:configure" in data["permissions"]
    assert "billing:manage" not in data["permissions"]
    assert "documents:view" not in data["permissions"]
