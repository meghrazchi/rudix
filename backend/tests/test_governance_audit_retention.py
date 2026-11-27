"""R04-09: organisation audit log retention override through PATCH /admin/governance."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.enums import OrganizationRole
from app.models.governance import OrganizationGovernancePolicy
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User

pytestmark = pytest.mark.both_dialects

URL = "/api/v1/admin/governance"
ACTION = "admin.governance.policy.updated"


@pytest_asyncio.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "retention_audit_logs_days", None)
    get_auth_provider.cache_clear()

    async def _override() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        finally:
            # Every request gets a fresh session in the app; this harness shares one, so drop
            # the tenant binding (and the strict-mode ORM guard, RLS default since 0.5.0) that
            # a request left on it before the test reads through the same session.
            db_session.info.pop("organization_id", None)
            db_session.info.pop("enforce_tenant_guard", None)

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        yield http_client
    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


async def _principal(
    session: AsyncSession, role: OrganizationRole
) -> tuple[dict[str, str], Organization]:
    suffix = uuid4().hex
    org = Organization(name=f"Audit retention {suffix}", slug=f"audit-retention-{suffix}")
    session.add(org)
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"audit-retention-{suffix}",
        email=f"audit-retention-{suffix}@example.com",
    )
    session.add(user)
    await session.flush()
    session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await session.commit()
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}, org


async def _stored(session: AsyncSession, org: Organization) -> OrganizationGovernancePolicy | None:
    result = await session.execute(
        select(OrganizationGovernancePolicy).where(
            OrganizationGovernancePolicy.organization_id == org.id
        )
    )
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_admin_sets_and_clears_override_with_audit_entry(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, org = await _principal(db_session, OrganizationRole.admin)

    initial = await client.get(URL, headers=headers)
    assert initial.status_code == 200
    body = initial.json()
    assert body["policy"]["audit_log_retention_days"] is None
    assert body["platform_audit_log_retention_days"] is None
    assert body["effective_audit_log_retention_days"] is None

    response = await client.patch(URL, headers=headers, json={"audit_log_retention_days": 90})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["policy"]["audit_log_retention_days"] == 90
    assert body["effective_audit_log_retention_days"] == 90
    assert body["changed_fields"] == ["audit_log_retention_days"]
    assert body["audit_recorded"] is True
    stored = await _stored(db_session, org)
    assert stored is not None and stored.audit_log_retention_days == 90

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.organization_id == org.id, AuditLog.action == ACTION
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].metadata_json["audit_log_retention_days"] == 90
    assert audit[0].metadata_json["effective_audit_log_retention_days"] == 90

    # Omitting the field keeps the override.
    unchanged = await client.patch(URL, headers=headers, json={"agentic_mode_enabled": True})
    assert unchanged.status_code == 200
    assert unchanged.json()["policy"]["audit_log_retention_days"] == 90

    # An explicit null clears it; the platform default applies again.
    monkeypatch.setattr(settings, "retention_audit_logs_days", 365)
    cleared = await client.patch(URL, headers=headers, json={"audit_log_retention_days": None})
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["policy"]["audit_log_retention_days"] is None
    assert body["platform_audit_log_retention_days"] == 365
    assert body["effective_audit_log_retention_days"] == 365
    stored = await _stored(db_session, org)
    assert stored is not None
    await db_session.refresh(stored)
    assert stored.audit_log_retention_days is None


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [0, 7, 29, 3651, "abc"])
async def test_override_validation_rejects_out_of_range(
    client: AsyncClient, db_session: AsyncSession, days: object
) -> None:
    headers, org = await _principal(db_session, OrganizationRole.owner)

    response = await client.patch(URL, headers=headers, json={"audit_log_retention_days": days})

    assert response.status_code == 422
    assert await _stored(db_session, org) is None


@pytest.mark.asyncio
async def test_override_floor_accepted(client: AsyncClient, db_session: AsyncSession) -> None:
    headers, _ = await _principal(db_session, OrganizationRole.owner)

    response = await client.patch(URL, headers=headers, json={"audit_log_retention_days": 30})

    assert response.status_code == 200
    assert response.json()["policy"]["audit_log_retention_days"] == 30


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [OrganizationRole.member, OrganizationRole.viewer])
async def test_non_admin_roles_forbidden(
    client: AsyncClient, db_session: AsyncSession, role: OrganizationRole
) -> None:
    headers, org = await _principal(db_session, role)

    response = await client.patch(URL, headers=headers, json={"audit_log_retention_days": 90})

    assert response.status_code == 403
    assert await _stored(db_session, org) is None


@pytest.mark.asyncio
async def test_override_is_isolated_per_organisation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers_a, org_a = await _principal(db_session, OrganizationRole.admin)
    headers_b, org_b = await _principal(db_session, OrganizationRole.admin)

    response = await client.patch(URL, headers=headers_a, json={"audit_log_retention_days": 60})
    assert response.status_code == 200

    other = await client.get(URL, headers=headers_b)
    assert other.status_code == 200
    assert other.json()["organization_id"] == str(org_b.id)
    assert other.json()["policy"]["audit_log_retention_days"] is None
    assert await _stored(db_session, org_b) is None

    # A token for org A cannot target org B by switching the organisation header.
    spoofed = {**headers_a, "X-Organization-ID": str(org_b.id)}
    blocked = await client.patch(URL, headers=spoofed, json={"audit_log_retention_days": 30})
    assert blocked.status_code in {401, 403}
    assert await _stored(db_session, org_b) is None
    stored_a = await _stored(db_session, org_a)
    assert stored_a is not None and stored_a.audit_log_retention_days == 60


@pytest.mark.asyncio
async def test_database_check_constraint_enforces_floor(db_session: AsyncSession) -> None:
    suffix = uuid4().hex
    org = Organization(name=f"Floor {suffix}", slug=f"floor-{suffix}")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        OrganizationGovernancePolicy(organization_id=org.id, audit_log_retention_days=29)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
