"""Backend tests for F278: team management, invitations, roles, and member lifecycle."""

import os
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
from app.domains.team.services.invitation_service import (
    generate_invite_token,
    hash_invite_token,
    invite_expires_at,
)
from app.domains.quota.services.quota_service import upsert_policy_with_log
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_invitation import OrganizationInvitation
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

    async def _override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_org(db_session: AsyncSession, *, name: str | None = None) -> Organization:
    slug = f"org-{uuid4().hex[:8]}"
    org = Organization(name=name or slug, slug=slug)
    db_session.add(org)
    await db_session.flush()
    return org


async def _seed_member(
    db_session: AsyncSession,
    *,
    org: Organization,
    role: OrganizationRole,
    invited: bool = False,
    email_prefix: str = "user",
) -> tuple[User, OrganizationMember]:
    user = User(
        organization_id=org.id,
        external_auth_id=(f"invite::{uuid4()}" if invited else f"user-{uuid4().hex[:8]}"),
        email=f"{email_prefix}-{uuid4().hex[:8]}@example.com",
        display_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()
    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=role.value,
    )
    db_session.add(member)
    await db_session.commit()
    return user, member


async def _seed_invitation(
    db_session: AsyncSession,
    *,
    org: Organization,
    email: str,
    role: str = "member",
    invited_by_user_id=None,
    member_id=None,
    token: str | None = None,
) -> tuple[str, OrganizationInvitation]:
    raw_token = token or generate_invite_token()
    inv = OrganizationInvitation(
        organization_id=org.id,
        email=email,
        role=role,
        token_hash=hash_invite_token(raw_token),
        status="pending",
        expires_at=invite_expires_at(),
        invited_by_user_id=invited_by_user_id,
        member_id=member_id,
        resend_count=0,
    )
    db_session.add(inv)
    await db_session.commit()
    return raw_token, inv


async def _seed_quota_policy(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    limits: dict[str, dict[str, object]],
) -> None:
    await upsert_policy_with_log(
        db_session,
        organization_id=organization_id,
        limits=limits,
        updated_by_id=None,
        change_note="test quota policy",
    )
    await db_session.commit()


def _auth_headers(*, token: str, org_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}


async def _actor_token(
    db_session: AsyncSession,
    *,
    org: Organization,
    role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, str]:
    user, _ = await _seed_member(db_session, org=org, role=role)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    return user, token


# ─── Member listing with search and filters ──────────────────────────────────


@pytest.mark.asyncio
async def test_list_members_with_search(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org)
    user_a, _ = await _seed_member(
        db_session, org=org, role=OrganizationRole.member, email_prefix="alice"
    )
    user_b, _ = await _seed_member(
        db_session, org=org, role=OrganizationRole.viewer, email_prefix="bob"
    )

    resp = await team_client.get(
        "/api/v1/team/members",
        headers=_auth_headers(token=token, org_id=str(org.id)),
        params={"search": "alice"},
    )
    assert resp.status_code == 200
    emails = {item["email"] for item in resp.json()["items"]}
    assert any("alice" in e for e in emails)
    assert not any("bob" in e for e in emails)


@pytest.mark.asyncio
async def test_list_members_role_filter(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org)
    await _seed_member(db_session, org=org, role=OrganizationRole.member)
    await _seed_member(db_session, org=org, role=OrganizationRole.viewer)

    resp = await team_client.get(
        "/api/v1/team/members",
        headers=_auth_headers(token=token, org_id=str(org.id)),
        params={"role": "viewer"},
    )
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["role"] == "viewer"


# ─── Member detail endpoint ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_member_detail(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org)
    target_user, target_member = await _seed_member(
        db_session, org=org, role=OrganizationRole.member
    )

    resp = await team_client.get(
        f"/api/v1/team/members/{target_member.id}",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["member_id"] == str(target_member.id)
    assert payload["email"] == target_user.email
    assert "is_active" in payload
    assert "provisioned_by" in payload


@pytest.mark.asyncio
async def test_get_member_detail_tenant_isolation(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org_a = await _seed_org(db_session)
    org_b = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org_a)
    _, other_member = await _seed_member(db_session, org=org_b, role=OrganizationRole.member)

    resp = await team_client.get(
        f"/api/v1/team/members/{other_member.id}",
        headers=_auth_headers(token=token, org_id=str(org_a.id)),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invite_team_member_blocks_when_seat_limit_is_reached(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    _, token = await _actor_token(db_session, org=org, role=OrganizationRole.admin)
    await _seed_quota_policy(
        db_session,
        organization_id=org.id,
        limits={
            "seats": {
                "soft_limit": 1,
                "hard_limit": 1,
                "reset_window": "none",
            }
        },
    )

    response = await team_client.post(
        "/api/v1/team/members/invite",
        headers=_auth_headers(token=token, org_id=str(org.id)),
        json={"email": "new-seat@example.com", "role": OrganizationRole.member.value},
    )

    assert response.status_code == 403
    payload = response.json()["detail"]
    assert payload["code"] == "plan_limit_exceeded"
    assert payload["quota_type"] == "seats"
    assert payload["retryable"] is False
    assert payload["action"] == "Remove a member or upgrade your plan."


# ─── Last-owner protection ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cannot_remove_last_owner(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    owner_user, owner_member = await _seed_member(db_session, org=org, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=owner_user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await team_client.delete(
        f"/api/v1/team/members/{owner_member.id}",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 409
    assert "owner" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_deactivate_last_owner(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    owner_user, owner_member = await _seed_member(db_session, org=org, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=owner_user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await team_client.post(
        f"/api/v1/team/members/{owner_member.id}/deactivate",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 409
    assert "last owner" in resp.json()["detail"].lower()


# ─── Deactivate member ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deactivate_member(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org, role=OrganizationRole.admin)
    target_user, target_member = await _seed_member(
        db_session, org=org, role=OrganizationRole.member
    )

    resp = await team_client.post(
        f"/api/v1/team/members/{target_member.id}/deactivate",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["is_active"] is False

    await db_session.refresh(target_user)
    assert target_user.is_active is False


# ─── Invitation listing ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_invitations_returns_pending_only(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org)
    await _seed_invitation(
        db_session, org=org, email="pending@example.com", invited_by_user_id=actor.id
    )

    revoked_inv = OrganizationInvitation(
        organization_id=org.id,
        email="revoked@example.com",
        role="member",
        token_hash=hash_invite_token(generate_invite_token()),
        status="revoked",
        expires_at=invite_expires_at(),
    )
    db_session.add(revoked_inv)
    await db_session.commit()

    resp = await team_client.get(
        "/api/v1/team/invitations",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 200
    payload = resp.json()
    emails = {item["email"] for item in payload["items"]}
    assert "pending@example.com" in emails
    assert "revoked@example.com" not in emails


@pytest.mark.asyncio
async def test_list_invitations_tenant_isolation(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org_a = await _seed_org(db_session)
    org_b = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org_a)
    await _seed_invitation(db_session, org=org_b, email="other@example.com")

    resp = await team_client.get(
        "/api/v1/team/invitations",
        headers=_auth_headers(token=token, org_id=str(org_a.id)),
    )
    assert resp.status_code == 200
    emails = {item["email"] for item in resp.json()["items"]}
    assert "other@example.com" not in emails


# ─── Revoke invitation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_invitation(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org)
    _, inv = await _seed_invitation(
        db_session, org=org, email="target@example.com", invited_by_user_id=actor.id
    )

    resp = await team_client.post(
        f"/api/v1/team/invitations/{inv.id}/revoke",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True

    await db_session.refresh(inv)
    assert inv.status == "revoked"
    assert inv.revoked_at is not None
    assert inv.revoked_by_user_id == actor.id


@pytest.mark.asyncio
async def test_revoke_already_revoked_invitation_returns_409(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org)
    _, inv = await _seed_invitation(db_session, org=org, email="target2@example.com")
    inv.status = "revoked"
    await db_session.commit()

    resp = await team_client.post(
        f"/api/v1/team/invitations/{inv.id}/revoke",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 409


# ─── Resend invitation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resend_invitation_updates_token_hash(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org)
    _, inv = await _seed_invitation(db_session, org=org, email="resend@example.com")
    original_hash = inv.token_hash

    from unittest.mock import patch

    with patch("app.workers.email_tasks.dispatch_email"):
        resp = await team_client.post(
            f"/api/v1/team/invitations/{inv.id}/resend",
            headers=_auth_headers(token=token, org_id=str(org.id)),
        )
    assert resp.status_code == 200
    assert resp.json()["resent"] is True

    await db_session.refresh(inv)
    assert inv.token_hash != original_hash
    assert inv.resend_count == 1


# ─── Accept invitation (public) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_accept_invitation_marks_accepted(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    email = f"acceptme-{uuid4().hex[:6]}@example.com"
    user = User(
        organization_id=org.id,
        external_auth_id=f"invite::{uuid4()}",
        email=email,
        display_name="Acceptor",
    )
    db_session.add(user)
    await db_session.flush()
    raw_token, inv = await _seed_invitation(
        db_session, org=org, email=email, invited_by_user_id=None
    )

    resp = await team_client.post(
        "/api/v1/team/invitations/accept",
        json={"token": raw_token},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["accepted"] is True
    assert payload["email"] == email

    await db_session.refresh(inv)
    assert inv.status == "accepted"
    assert inv.accepted_at is not None


@pytest.mark.asyncio
async def test_accept_invitation_expired_returns_410(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    from datetime import UTC, datetime, timedelta

    org = await _seed_org(db_session)
    raw_token = generate_invite_token()
    inv = OrganizationInvitation(
        organization_id=org.id,
        email=f"expired-{uuid4().hex[:6]}@example.com",
        role="member",
        token_hash=hash_invite_token(raw_token),
        status="pending",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(inv)
    await db_session.commit()

    resp = await team_client.post(
        "/api/v1/team/invitations/accept",
        json={"token": raw_token},
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_accept_invitation_invalid_token_returns_404(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    resp = await team_client.post(
        "/api/v1/team/invitations/accept",
        json={"token": generate_invite_token()},
    )
    assert resp.status_code == 404


# ─── Token security – token hash is never in API response ────────────────────


@pytest.mark.asyncio
async def test_invitation_list_does_not_expose_token_hash(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org)
    raw_token = generate_invite_token()
    _, inv = await _seed_invitation(db_session, org=org, email="sec@example.com", token=raw_token)

    resp = await team_client.get(
        "/api/v1/team/invitations",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 200
    body_text = resp.text
    assert raw_token not in body_text
    assert inv.token_hash not in body_text


# ─── Invite creates invitation record ────────────────────────────────────────


@pytest.mark.asyncio
async def test_invite_endpoint_creates_invitation_record(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, token = await _actor_token(db_session, org=org, role=OrganizationRole.owner)

    from unittest.mock import patch

    with patch("app.workers.email_tasks.dispatch_email"):
        resp = await team_client.post(
            "/api/v1/team/members/invite",
            headers=_auth_headers(token=token, org_id=str(org.id)),
            json={"email": "newuser@example.com", "role": "member"},
        )
    assert resp.status_code == 201
    assert resp.json()["invited"] is True

    from sqlalchemy import select

    result = await db_session.execute(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == org.id,
            OrganizationInvitation.email == "newuser@example.com",
        )
    )
    inv = result.scalar_one_or_none()
    assert inv is not None
    assert inv.status == "pending"
    assert inv.token_hash  # hashed token stored
    # The raw token is not stored
    assert len(inv.token_hash) == 64  # SHA-256 hex digest


# ─── RBAC enforcement ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_member_cannot_list_invitations(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    user, _ = await _seed_member(db_session, org=org, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    resp = await team_client.get(
        "/api/v1/team/invitations",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_revoke_invitations(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    user, _ = await _seed_member(db_session, org=org, role=OrganizationRole.member)
    _, inv = await _seed_invitation(db_session, org=org, email="x@example.com")
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    resp = await team_client.post(
        f"/api/v1/team/invitations/{inv.id}/revoke",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_deactivate_members(
    team_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org = await _seed_org(db_session)
    actor, _ = await _seed_member(db_session, org=org, role=OrganizationRole.member)
    target, target_member = await _seed_member(db_session, org=org, role=OrganizationRole.viewer)
    token = create_app_access_token(
        subject=actor.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    resp = await team_client.post(
        f"/api/v1/team/members/{target_member.id}/deactivate",
        headers=_auth_headers(token=token, org_id=str(org.id)),
    )
    assert resp.status_code == 403


# ─── Invitation service unit tests ───────────────────────────────────────────


def test_token_hash_is_deterministic() -> None:
    token = generate_invite_token()
    h1 = hash_invite_token(token)
    h2 = hash_invite_token(token)
    assert h1 == h2
    assert len(h1) == 64


def test_different_tokens_produce_different_hashes() -> None:
    t1 = generate_invite_token()
    t2 = generate_invite_token()
    assert t1 != t2
    assert hash_invite_token(t1) != hash_invite_token(t2)


def test_invite_expires_at_is_future() -> None:
    from datetime import UTC, datetime

    exp = invite_expires_at()
    assert exp > datetime.now(UTC)
