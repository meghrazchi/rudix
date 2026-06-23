import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure strict settings can be loaded when importing modules in tests.
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
async def team_client(
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


async def _seed_member(
    db_session: AsyncSession,
    *,
    organization: Organization,
    role: OrganizationRole,
    email_prefix: str = "member",
    invited: bool = False,
) -> User:
    user = User(
        organization_id=organization.id,
        external_auth_id=(f"invite::{uuid4()}" if invited else f"user-{uuid4().hex[:8]}"),
        email=f"{email_prefix}-{uuid4().hex[:8]}@example.com",
        display_name="Org User",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user


async def _seed_context(
    db_session: AsyncSession,
    *,
    actor_role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Team Primary", slug=f"team-primary-{uuid4().hex[:8]}")
    secondary_org = Organization(name="Team Secondary", slug=f"team-secondary-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, secondary_org])
    await db_session.flush()

    actor = User(
        organization_id=primary_org.id,
        external_auth_id=f"actor-{uuid4().hex[:8]}",
        email=f"actor-{uuid4().hex[:8]}@example.com",
        display_name="Actor User",
    )
    db_session.add(actor)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=primary_org.id,
            user_id=actor.id,
            role=actor_role.value,
        )
    )
    await db_session.commit()
    return actor, primary_org, secondary_org


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
async def test_list_team_members_returns_org_scoped_members(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, primary_org, _ = await _seed_context(db_session, actor_role=OrganizationRole.admin)
    active_user = await _seed_member(
        db_session,
        organization=primary_org,
        role=OrganizationRole.member,
        email_prefix="active",
    )
    invited_user = await _seed_member(
        db_session,
        organization=primary_org,
        role=OrganizationRole.viewer,
        email_prefix="invited",
        invited=True,
    )
    token = create_app_access_token(
        subject=actor.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )

    response = await team_client.get(
        "/api/v1/team/members",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
        params={"limit": 20, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    emails = {item["email"]: item for item in payload["items"]}
    assert active_user.email in emails
    assert invited_user.email in emails
    assert emails[active_user.email]["status"] == "active"
    assert emails[invited_user.email]["status"] == "invited"


@pytest.mark.asyncio
async def test_list_team_members_rejects_member_role(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, primary_org, _ = await _seed_context(db_session, actor_role=OrganizationRole.member)
    token = create_app_access_token(
        subject=actor.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )

    response = await team_client.get(
        "/api/v1/team/members",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions for requested operation"


@pytest.mark.asyncio
async def test_invite_team_member_creates_invited_membership(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, primary_org, _ = await _seed_context(db_session, actor_role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=actor.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )

    response = await team_client.post(
        "/api/v1/team/members/invite",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
        json={"email": "teammate@example.com", "role": "viewer"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["invited"] is True
    assert payload["member"]["email"] == "teammate@example.com"
    assert payload["member"]["role"] == "viewer"
    assert payload["member"]["status"] == "invited"


@pytest.mark.asyncio
async def test_update_and_remove_member_respect_conflict_rules(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, primary_org, _ = await _seed_context(db_session, actor_role=OrganizationRole.admin)
    removable_user = await _seed_member(
        db_session,
        organization=primary_org,
        role=OrganizationRole.member,
        email_prefix="removable",
    )
    owner_user = await _seed_member(
        db_session,
        organization=primary_org,
        role=OrganizationRole.owner,
        email_prefix="owner",
    )
    token = create_app_access_token(
        subject=actor.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )

    list_response = await team_client.get(
        "/api/v1/team/members",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
        params={"limit": 50, "offset": 0},
    )
    assert list_response.status_code == 200
    members_by_email = {item["email"]: item for item in list_response.json()["items"]}
    removable_member_id = members_by_email[removable_user.email]["member_id"]
    owner_member_id = members_by_email[owner_user.email]["member_id"]

    update_response = await team_client.patch(
        f"/api/v1/team/members/{removable_member_id}/role",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
        json={"role": "viewer"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["role"] == "viewer"

    remove_response = await team_client.delete(
        f"/api/v1/team/members/{removable_member_id}",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
    )
    assert remove_response.status_code == 200
    assert remove_response.json()["removed"] is True

    update_owner_response = await team_client.patch(
        f"/api/v1/team/members/{owner_member_id}/role",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
        json={"role": "admin"},
    )
    assert update_owner_response.status_code == 409
    assert update_owner_response.json()["detail"] == "Owner role cannot be changed"

    remove_owner_response = await team_client.delete(
        f"/api/v1/team/members/{owner_member_id}",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
    )
    assert remove_owner_response.status_code == 409
    assert remove_owner_response.json()["detail"] == "Cannot remove the last owner"
