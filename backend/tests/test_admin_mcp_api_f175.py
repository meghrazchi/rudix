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
) -> tuple[User, Organization]:
    org = Organization(name=f"Org-{uuid4().hex[:8]}", slug=f"org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Test Admin",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


# ─── GET /admin/mcp/policy ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_mcp_policy_returns_defaults_for_new_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/mcp/policy",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["read_only"] is True
    assert data["rate_limit_enabled"] is True
    assert data["rate_limit_requests"] == 30
    assert data["rate_limit_window_seconds"] == 60
    assert data["organization_id"] == str(org.id)


@pytest.mark.asyncio
async def test_get_mcp_policy_forbidden_for_non_admin(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    response = await admin_client.get(
        "/admin/mcp/policy",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ─── PATCH /admin/mcp/policy ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_mcp_policy_enabled(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={"enabled": True, "read_only": False},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["read_only"] is False


@pytest.mark.asyncio
async def test_update_mcp_policy_rate_limits(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={"rate_limit_requests": 100, "rate_limit_window_seconds": 120},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["rate_limit_requests"] == 100
    assert data["rate_limit_window_seconds"] == 120


@pytest.mark.asyncio
async def test_update_mcp_policy_invalid_rate_limit(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={"rate_limit_requests": 99999},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_mcp_policy_persists(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    headers = _auth_headers(token=token, organization_id=str(org.id))

    await admin_client.patch(
        "/admin/mcp/policy", json={"enabled": True, "read_only": True}, headers=headers
    )

    response = await admin_client.get("/admin/mcp/policy", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["read_only"] is True


@pytest.mark.asyncio
async def test_update_mcp_policy_capabilities(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={
            "capabilities_viewer": ["documents.read"],
            "capabilities_admin": ["documents.read", "chat.answer"],
        },
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["capabilities_viewer"] == ["documents.read"]
    assert data["capabilities_admin"] == ["documents.read", "chat.answer"]


@pytest.mark.asyncio
async def test_update_mcp_policy_forbidden_for_member(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    response = await admin_client.patch(
        "/admin/mcp/policy",
        json={"enabled": True},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_mcp_policy_org_isolation(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_principal(db_session, role=OrganizationRole.admin)
    user_b, org_b = await _seed_principal(db_session, role=OrganizationRole.admin)
    token_a = create_app_access_token(
        user_id=str(user_a.id), organization_id=str(org_a.id), role=OrganizationRole.admin.value
    )
    token_b = create_app_access_token(
        user_id=str(user_b.id), organization_id=str(org_b.id), role=OrganizationRole.admin.value
    )

    await admin_client.patch(
        "/admin/mcp/policy",
        json={"enabled": True},
        headers=_auth_headers(token=token_a, organization_id=str(org_a.id)),
    )

    response_b = await admin_client.get(
        "/admin/mcp/policy",
        headers=_auth_headers(token=token_b, organization_id=str(org_b.id)),
    )
    assert response_b.status_code == 200
    assert response_b.json()["enabled"] is False  # org B unaffected


# ─── GET /admin/mcp/status ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_mcp_status_returns_expected_shape(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/mcp/status",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert "feature_enabled" in data
    assert "transport" in data
    assert "dependencies" in data
    assert "failed_dependencies" in data
    assert isinstance(data["failed_dependencies"], list)


@pytest.mark.asyncio
async def test_get_mcp_status_forbidden_for_member(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    response = await admin_client.get(
        "/admin/mcp/status",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ─── GET /admin/mcp/tools ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_mcp_tools_returns_list(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_mcp", False)
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/mcp/tools",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_list_mcp_tools_forbidden_for_member(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    response = await admin_client.get(
        "/admin/mcp/tools",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ─── GET /admin/mcp/audit-events ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_mcp_audit_events_empty(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/mcp/audit-events",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_mcp_audit_events_after_policy_update(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    headers = _auth_headers(token=token, organization_id=str(org.id))

    await admin_client.patch("/admin/mcp/policy", json={"enabled": True}, headers=headers)

    response = await admin_client.get("/admin/mcp/audit-events", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(e["action"] == "mcp.policy.updated" for e in data["items"])


@pytest.mark.asyncio
async def test_list_mcp_audit_events_forbidden_for_member(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    response = await admin_client.get(
        "/admin/mcp/audit-events",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_mcp_audit_events_org_isolation(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_principal(db_session, role=OrganizationRole.admin)
    user_b, org_b = await _seed_principal(db_session, role=OrganizationRole.admin)
    token_a = create_app_access_token(
        user_id=str(user_a.id), organization_id=str(org_a.id), role=OrganizationRole.admin.value
    )
    token_b = create_app_access_token(
        user_id=str(user_b.id), organization_id=str(org_b.id), role=OrganizationRole.admin.value
    )

    await admin_client.patch(
        "/admin/mcp/policy",
        json={"enabled": True},
        headers=_auth_headers(token=token_a, organization_id=str(org_a.id)),
    )

    response_b = await admin_client.get(
        "/admin/mcp/audit-events",
        headers=_auth_headers(token=token_b, organization_id=str(org_b.id)),
    )
    assert response_b.status_code == 200
    assert response_b.json()["total"] == 0
