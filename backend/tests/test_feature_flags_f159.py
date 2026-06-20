"""Tests for F159: Feature flags and rollout controls.

Covers:
  - Flag resolution precedence (env default → org override)
  - ALL_FLAG_NAMES and env-default mapping completeness
  - Admin API: list, set, clear flags
  - Admin API: 403 for non-admin roles
  - User-facing /feature-flags endpoint returns resolved values
  - require_feature dependency blocks disabled-flag requests
  - Audit log written on set/clear
  - Flag changes are safe to roll back (clear restores env default)
"""

from __future__ import annotations

import os
from typing import Annotated
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
from app.domains.admin.schemas.feature_flags import ALL_FLAG_NAMES
from app.domains.admin.services.feature_flag_service import (
    _SETTINGS_ATTR,
    FeatureFlagService,
    _env_default,
)
from app.main import app
from app.models.enums import OrganizationRole
from app.models.feature_flags import OrgFeatureFlagOverride
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User

# ---------------------------------------------------------------------------
# Unit tests: flag resolution
# ---------------------------------------------------------------------------


def test_all_flag_names_have_settings_mapping() -> None:
    """Every canonical flag name must map to a real settings attribute."""
    for name in ALL_FLAG_NAMES:
        assert name in _SETTINGS_ATTR, f"Flag {name!r} has no settings mapping"
        attr = _SETTINGS_ATTR[name]
        assert hasattr(settings, attr), f"settings has no attribute {attr!r} (for flag {name!r})"


def test_env_default_returns_bool_for_all_flags() -> None:
    for name in ALL_FLAG_NAMES:
        result = _env_default(name)
        assert isinstance(result, bool), f"_env_default({name!r}) returned {type(result)}"


def test_env_default_unknown_flag_returns_false() -> None:
    assert _env_default("nonexistent_flag_xyz") is False


def test_flag_names_are_unique() -> None:
    assert len(ALL_FLAG_NAMES) == len(set(ALL_FLAG_NAMES))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ff_client(
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def _seed_principal(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
) -> tuple[User, Organization]:
    org = Organization(
        name=f"FF Org {uuid4().hex[:6]}",
        slug=f"ff-org-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"ff-user-{uuid4().hex[:8]}",
        email=f"ff-{uuid4().hex[:8]}@example.com",
        display_name="FF User",
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


def _auth(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


# ---------------------------------------------------------------------------
# Admin API: list flags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_flags_returns_all_flags_for_admin(
    ff_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await ff_client.get(
        "/api/v1/admin/feature-flags",
        headers=_auth(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["organization_id"] == str(org.id)
    returned_names = {f["name"] for f in body["flags"]}
    assert returned_names == set(ALL_FLAG_NAMES)
    for flag in body["flags"]:
        assert "enabled" in flag
        assert "env_default" in flag
        assert "has_org_override" in flag
        assert flag["has_org_override"] is False


@pytest.mark.asyncio
async def test_list_flags_forbidden_for_developer(
    ff_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.developer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await ff_client.get(
        "/api/v1/admin/feature-flags",
        headers=_auth(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_flags_forbidden_for_viewer(
    ff_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.viewer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await ff_client.get(
        "/api/v1/admin/feature-flags",
        headers=_auth(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Admin API: set flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_flag_creates_override_and_audits(
    ff_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    flag_name = "evaluations"
    response = await ff_client.put(
        f"/api/v1/admin/feature-flags/{flag_name}",
        headers=_auth(token=token, organization_id=str(org.id)),
        json={"enabled": False, "reason": "Rollout paused for compliance review"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["flag"]["name"] == flag_name
    assert body["flag"]["enabled"] is False
    assert body["flag"]["has_org_override"] is True
    assert body["flag"]["override_reason"] == "Rollout paused for compliance review"

    # Verify DB row created
    from sqlalchemy import select

    override = (
        await db_session.execute(
            select(OrgFeatureFlagOverride).where(
                OrgFeatureFlagOverride.organization_id == org.id,
                OrgFeatureFlagOverride.flag_name == flag_name,
            )
        )
    ).scalar_one_or_none()
    assert override is not None
    assert override.enabled is False

    # Verify audit log
    from sqlalchemy import select

    audit = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.organization_id == org.id)
                .order_by(AuditLog.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert audit is not None
    assert audit.action == "admin.feature_flag.override.set"


@pytest.mark.asyncio
async def test_set_flag_unknown_name_returns_404(
    ff_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await ff_client.put(
        "/api/v1/admin/feature-flags/does_not_exist",
        headers=_auth(token=token, organization_id=str(org.id)),
        json={"enabled": True},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_flag_forbidden_for_developer(
    ff_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.developer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await ff_client.put(
        "/api/v1/admin/feature-flags/evaluations",
        headers=_auth(token=token, organization_id=str(org.id)),
        json={"enabled": False},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Admin API: clear flag (roll back)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_flag_reverts_to_env_default_and_audits(
    ff_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Set mcp to env-disabled so we have a known default to assert against
    monkeypatch.setattr(settings, "feature_enable_mcp", False)

    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    # First enable via override
    await ff_client.put(
        "/api/v1/admin/feature-flags/mcp",
        headers=_auth(token=token, organization_id=str(org.id)),
        json={"enabled": True, "reason": "Pilot"},
    )

    # Now clear the override
    response = await ff_client.delete(
        "/api/v1/admin/feature-flags/mcp",
        headers=_auth(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reverted_to_env_default"] is True
    assert body["env_default"] is False

    # Verify no override row remains
    from sqlalchemy import select

    override = (
        await db_session.execute(
            select(OrgFeatureFlagOverride).where(
                OrgFeatureFlagOverride.organization_id == org.id,
                OrgFeatureFlagOverride.flag_name == "mcp",
            )
        )
    ).scalar_one_or_none()
    assert override is None

    # Verify audit log for clear
    from sqlalchemy import select

    audit = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(
                    AuditLog.organization_id == org.id,
                    AuditLog.action == "admin.feature_flag.override.cleared",
                )
                .order_by(AuditLog.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_clear_nonexistent_flag_returns_404(
    ff_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await ff_client.delete(
        "/api/v1/admin/feature-flags/not_a_real_flag",
        headers=_auth(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# User-facing /feature-flags endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_feature_flags_returns_all_resolved_flags(
    ff_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.developer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await ff_client.get(
        "/api/v1/feature-flags",
        headers=_auth(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    body = response.json()
    flags = body["flags"]
    for name in ALL_FLAG_NAMES:
        assert name in flags, f"Flag {name!r} missing from public response"
        assert isinstance(flags[name], bool)


@pytest.mark.asyncio
async def test_public_feature_flags_reflects_org_override(
    ff_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_evaluations", True)
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    # Override evaluations to disabled
    await ff_client.put(
        "/api/v1/admin/feature-flags/evaluations",
        headers=_auth(token=token, organization_id=str(org.id)),
        json={"enabled": False, "reason": "Test override"},
    )

    response = await ff_client.get(
        "/api/v1/feature-flags",
        headers=_auth(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["flags"]["evaluations"] is False


# ---------------------------------------------------------------------------
# require_feature dependency: API cannot bypass a disabled flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_feature_blocks_request_when_flag_disabled(
    ff_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A protected endpoint must return 403 when its flag is disabled for the org."""
    from fastapi import APIRouter, Depends

    from app.auth.dependencies import get_current_principal, require_feature
    from app.auth.models import AuthenticatedPrincipal

    # Temporarily mount a test endpoint that requires the "evaluations" flag
    test_router = APIRouter()

    @test_router.get("/test-require-feature-evaluations")
    async def _guarded(
        _flag: Annotated[None, Depends(require_feature("evaluations"))],
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    ) -> dict:
        return {"ok": True}

    app.include_router(test_router, prefix="/api/v1")

    monkeypatch.setattr(settings, "feature_enable_evaluations", True)
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    # Disable via org override
    await ff_client.put(
        "/api/v1/admin/feature-flags/evaluations",
        headers=_auth(token=token, organization_id=str(org.id)),
        json={"enabled": False},
    )

    # The guarded endpoint should now return 403
    response = await ff_client.get(
        "/api/v1/test-require-feature-evaluations",
        headers=_auth(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403
    assert "evaluations" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Service unit tests: resolution precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_is_enabled_returns_env_default_when_no_override(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_connectors", True)
    org = Organization(
        name=f"FF Svc Org {uuid4().hex[:6]}",
        slug=f"ff-svc-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()

    service = FeatureFlagService()
    result = await service.is_enabled(db_session, organization_id=org.id, flag_name="connectors")
    assert result is True


@pytest.mark.asyncio
async def test_service_is_enabled_org_override_wins_over_env(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_connectors", True)
    org = Organization(
        name=f"FF Svc Org {uuid4().hex[:6]}",
        slug=f"ff-svc2-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"svc-user-{uuid4().hex[:8]}",
        email=f"svc-{uuid4().hex[:8]}@example.com",
        display_name="Svc User",
    )
    db_session.add(user)
    await db_session.flush()

    service = FeatureFlagService()
    await service.set_flag(
        db_session,
        organization_id=org.id,
        flag_name="connectors",
        enabled=False,
        reason="Disabled by test",
        overridden_by_user_id=user.id,
    )

    result = await service.is_enabled(db_session, organization_id=org.id, flag_name="connectors")
    assert result is False


@pytest.mark.asyncio
async def test_service_clear_flag_restores_env_default(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_pipeline_explorer", True)
    org = Organization(
        name=f"FF Clear Org {uuid4().hex[:6]}",
        slug=f"ff-clr-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"clr-user-{uuid4().hex[:8]}",
        email=f"clr-{uuid4().hex[:8]}@example.com",
        display_name="Clr User",
    )
    db_session.add(user)
    await db_session.flush()

    service = FeatureFlagService()
    # Disable via override
    await service.set_flag(
        db_session,
        organization_id=org.id,
        flag_name="pipeline_explorer",
        enabled=False,
        reason="Test",
        overridden_by_user_id=user.id,
    )
    assert (
        await service.is_enabled(db_session, organization_id=org.id, flag_name="pipeline_explorer")
        is False
    )

    # Clear override → env default (True) wins
    result = await service.clear_flag(
        db_session,
        organization_id=org.id,
        flag_name="pipeline_explorer",
    )
    assert result.env_default is True
    assert result.reverted_to_env_default is True
    assert (
        await service.is_enabled(db_session, organization_id=org.id, flag_name="pipeline_explorer")
        is True
    )


@pytest.mark.asyncio
async def test_service_set_flag_raises_on_unknown_name(
    db_session: AsyncSession,
) -> None:
    org = Organization(
        name=f"FF Err Org {uuid4().hex[:6]}",
        slug=f"ff-err-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()

    service = FeatureFlagService()
    with pytest.raises(ValueError, match="Unknown feature flag"):
        await service.set_flag(
            db_session,
            organization_id=org.id,
            flag_name="not_a_flag",
            enabled=True,
            reason=None,
            overridden_by_user_id=None,
        )


# ---------------------------------------------------------------------------
# Org isolation: overrides of one org must not leak to another
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_override_is_org_scoped(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_agents", False)

    org_a = Organization(name=f"Org A {uuid4().hex[:4]}", slug=f"org-a-{uuid4().hex[:6]}")
    org_b = Organization(name=f"Org B {uuid4().hex[:4]}", slug=f"org-b-{uuid4().hex[:6]}")
    db_session.add_all([org_a, org_b])
    await db_session.flush()
    user_a = User(
        organization_id=org_a.id,
        external_auth_id=f"ua-{uuid4().hex}",
        email=f"ua-{uuid4().hex[:8]}@x.com",
        display_name="UA",
    )
    db_session.add(user_a)
    await db_session.flush()

    service = FeatureFlagService()
    # Enable agents for org_a only
    await service.set_flag(
        db_session,
        organization_id=org_a.id,
        flag_name="agents",
        enabled=True,
        reason="Pilot org A",
        overridden_by_user_id=user_a.id,
    )

    assert (
        await service.is_enabled(db_session, organization_id=org_a.id, flag_name="agents") is True
    )
    # org_b must still see env default (False)
    assert (
        await service.is_enabled(db_session, organization_id=org_b.id, flag_name="agents") is False
    )
