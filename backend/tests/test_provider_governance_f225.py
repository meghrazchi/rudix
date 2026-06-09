"""Tests for provider security and governance controls (F225).

Covers:
  A. local_only_mode blocks cloud providers via check_provider_governance
  B. cloud_fallback_allowed=False raises CloudFallbackDisabledError for cloud fallback
  C. allowed_provider_profiles allowlist blocks non-listed providers
  D. Provider within allowlist is accepted
  E. cloud_fallback_warning_acknowledged gate when disabling local_only_mode
  F. cloud_fallback_warning_acknowledged gate when re-enabling cloud_fallback
  G. Governance defaults: local_only=False, fallback=allowed, no provider allowlist
  H. GET /admin/governance returns provider_security in response
  I. PATCH /admin/governance persists provider_security fields
  J. PATCH /admin/governance returns 422 without acknowledgment when enabling cloud
  K. Viewer cannot write governance policy (role guard)
  L. Tenant isolation: governance for org A does not affect org B
  M. Warnings emitted when local_only_mode=True but cloud_fallback_allowed=True
  N. Warning emitted when local_only=True without retention acknowledgment
  O. Audit log records provider governance update
  P. check_provider_governance allows local provider in local_only mode
  Q. Empty allowed_provider_profiles means all providers are allowed
  R. Non-cloud fallback key allowed even when cloud_fallback_allowed=False
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
from app.domains.admin.schemas.governance import GovernancePolicyState, ProviderSecurityPolicy
from app.domains.admin.services.governance_service import GovernancePolicyService
from app.domains.ai.profile.schemas import ProfileSource, ResolvedTaskProfile, TaskType
from app.domains.ai.profile.service import check_provider_governance
from app.domains.ai.providers.errors import CloudFallbackDisabledError, ProviderNotAllowedError
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def gov_client(
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


async def _seed(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.owner,
) -> tuple[User, Organization]:
    org = Organization(
        name=f"GovOrg {uuid4().hex[:6]}",
        slug=f"gov-org-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"gov-user-{uuid4().hex[:8]}",
        email=f"gov-{uuid4().hex[:8]}@example.com",
        display_name="Gov User",
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


def _headers(*, token: str, org_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": org_id,
    }


def _token(user: User, org: Organization) -> str:
    return create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )


def _chat_profile(provider: str, fallback: str | None = None) -> ResolvedTaskProfile:
    return ResolvedTaskProfile(
        task_type=TaskType.chat,
        provider_type=provider,
        base_model="test-model",
        max_tokens=None,
        temperature=None,
        json_mode=False,
        streaming=True,
        fallback_provider_key=fallback,
        source=ProfileSource.env_default,
        version=0,
    )


# ---------------------------------------------------------------------------
# Unit tests: check_provider_governance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_A_local_only_mode_blocks_cloud_provider() -> None:
    """A. local_only_mode=True blocks a cloud (openai) provider."""
    policy = ProviderSecurityPolicy(local_only_mode=True, cloud_fallback_allowed=False)
    profile = _chat_profile("openai")
    with pytest.raises(ProviderNotAllowedError, match="local_only_mode"):
        check_provider_governance(profile, policy)


@pytest.mark.asyncio
async def test_B_cloud_fallback_disabled_raises_for_cloud_fallback() -> None:
    """B. cloud_fallback_allowed=False raises when fallback key is a cloud provider."""
    policy = ProviderSecurityPolicy(local_only_mode=True, cloud_fallback_allowed=False)
    profile = _chat_profile("local", fallback="openai")
    with pytest.raises(CloudFallbackDisabledError, match="cloud_fallback_disabled"):
        check_provider_governance(profile, policy)


@pytest.mark.asyncio
async def test_C_allowed_provider_profiles_blocks_non_listed() -> None:
    """C. Non-empty allowed_provider_profiles list blocks unlisted provider."""
    policy = ProviderSecurityPolicy(allowed_provider_profiles=["local"])
    profile = _chat_profile("openai")
    with pytest.raises(ProviderNotAllowedError, match="provider_not_allowed"):
        check_provider_governance(profile, policy)


@pytest.mark.asyncio
async def test_D_allowed_provider_profiles_permits_listed() -> None:
    """D. Provider in allowlist passes the governance check."""
    policy = ProviderSecurityPolicy(allowed_provider_profiles=["openai", "local"])
    profile = _chat_profile("openai")
    check_provider_governance(profile, policy)  # no exception


@pytest.mark.asyncio
async def test_P_local_only_mode_allows_local_provider() -> None:
    """P. local_only_mode=True still allows the local provider."""
    policy = ProviderSecurityPolicy(local_only_mode=True, cloud_fallback_allowed=False)
    profile = _chat_profile("local")
    check_provider_governance(profile, policy)  # no exception


@pytest.mark.asyncio
async def test_Q_empty_allowed_list_permits_any_provider() -> None:
    """Q. Empty allowed_provider_profiles means all providers are allowed."""
    policy = ProviderSecurityPolicy(allowed_provider_profiles=[])
    profile = _chat_profile("openai")
    check_provider_governance(profile, policy)  # no exception


@pytest.mark.asyncio
async def test_R_non_cloud_fallback_allowed_even_when_cloud_fallback_disabled() -> None:
    """R. A local fallback key is fine even when cloud_fallback_allowed=False."""
    policy = ProviderSecurityPolicy(cloud_fallback_allowed=False)
    profile = _chat_profile("local", fallback="local")
    check_provider_governance(profile, policy)  # no exception


# ---------------------------------------------------------------------------
# Unit tests: GovernancePolicyService warnings
# ---------------------------------------------------------------------------


def test_M_warning_when_local_only_and_cloud_fallback_both_enabled() -> None:
    """M. Service emits warning when local_only=True but cloud_fallback=True."""
    svc = GovernancePolicyService()
    state = GovernancePolicyState(
        agentic_mode_enabled=False,
        mcp_exposure_enabled=False,
        allow_side_effect_tools=False,
        allowed_tool_names=[],
        budgets=svc._default_budget(),
        provider_security=ProviderSecurityPolicy(
            local_only_mode=True,
            cloud_fallback_allowed=True,
        ),
    )
    warnings = svc._resolve_warnings(policy_state=state)
    assert any("local_only_mode" in w and "cloud_fallback_allowed" in w for w in warnings)


def test_N_warning_when_local_only_without_retention_acknowledgment() -> None:
    """N. Warning emitted when local_only=True and retention not acknowledged."""
    svc = GovernancePolicyService()
    state = GovernancePolicyState(
        agentic_mode_enabled=False,
        mcp_exposure_enabled=False,
        allow_side_effect_tools=False,
        allowed_tool_names=[],
        budgets=svc._default_budget(),
        provider_security=ProviderSecurityPolicy(
            local_only_mode=True,
            cloud_fallback_allowed=False,
            retention_warning_acknowledged=False,
        ),
    )
    warnings = svc._resolve_warnings(policy_state=state)
    assert any("retention_warning_acknowledged" in w for w in warnings)


def test_no_warnings_when_local_only_mode_acknowledged() -> None:
    """No provider-security warnings when local_only=True and acknowledged."""
    svc = GovernancePolicyService()
    state = GovernancePolicyState(
        agentic_mode_enabled=False,
        mcp_exposure_enabled=False,
        allow_side_effect_tools=False,
        allowed_tool_names=[],
        budgets=svc._default_budget(),
        provider_security=ProviderSecurityPolicy(
            local_only_mode=True,
            cloud_fallback_allowed=False,
            retention_warning_acknowledged=True,
        ),
    )
    warnings = svc._resolve_warnings(policy_state=state)
    provider_warnings = [w for w in warnings if "local_only" in w or "retention" in w]
    assert provider_warnings == []


# ---------------------------------------------------------------------------
# HTTP integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_G_get_governance_returns_default_provider_security(
    gov_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """G. GET /admin/governance returns provider_security with safe defaults."""
    user, org = await _seed(db_session)
    tok = _token(user, org)

    resp = await gov_client.get(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
    )
    assert resp.status_code == 200
    ps = resp.json()["policy"]["provider_security"]
    assert ps["local_only_mode"] is False
    assert ps["cloud_fallback_allowed"] is True
    assert ps["allowed_provider_profiles"] == []
    assert ps["admin_only_model_selection"] is True


@pytest.mark.asyncio
async def test_H_patch_governance_persists_provider_security(
    gov_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """H. PATCH persists local_only_mode and allowed_provider_profiles."""
    user, org = await _seed(db_session)
    tok = _token(user, org)

    resp = await gov_client.patch(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
        json={
            "provider_security": {
                "local_only_mode": True,
                "cloud_fallback_allowed": False,
                "allowed_provider_profiles": ["local"],
                "admin_only_model_selection": True,
                "retention_warning_acknowledged": True,
            },
            "cloud_fallback_warning_acknowledged": True,
        },
    )
    assert resp.status_code == 200
    ps = resp.json()["policy"]["provider_security"]
    assert ps["local_only_mode"] is True
    assert ps["cloud_fallback_allowed"] is False
    assert ps["allowed_provider_profiles"] == ["local"]
    assert ps["retention_warning_acknowledged"] is True

    # Verify persisted by re-fetching
    get_resp = await gov_client.get(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
    )
    assert get_resp.json()["policy"]["provider_security"]["local_only_mode"] is True


@pytest.mark.asyncio
async def test_I_patch_enabling_cloud_without_acknowledgment_returns_422(
    gov_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """I. PATCH enabling cloud fallback from local-only without ack returns 422."""
    user, org = await _seed(db_session)
    tok = _token(user, org)

    # First set local-only
    await gov_client.patch(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
        json={
            "provider_security": {
                "local_only_mode": True,
                "cloud_fallback_allowed": False,
                "allowed_provider_profiles": [],
                "admin_only_model_selection": True,
                "retention_warning_acknowledged": True,
            },
            "cloud_fallback_warning_acknowledged": True,
        },
    )

    # Now try to disable local_only without acknowledgment
    resp = await gov_client.patch(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
        json={
            "provider_security": {
                "local_only_mode": False,
                "cloud_fallback_allowed": True,
                "allowed_provider_profiles": [],
                "admin_only_model_selection": True,
                "retention_warning_acknowledged": True,
            },
            # cloud_fallback_warning_acknowledged intentionally missing / false
        },
    )
    assert resp.status_code == 422
    assert "cloud_fallback_warning_acknowledged" in resp.text


@pytest.mark.asyncio
async def test_J_enabling_cloud_fallback_with_acknowledgment_succeeds(
    gov_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """J. PATCH with cloud_fallback_warning_acknowledged=True succeeds."""
    user, org = await _seed(db_session)
    tok = _token(user, org)

    await gov_client.patch(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
        json={
            "provider_security": {
                "local_only_mode": True,
                "cloud_fallback_allowed": False,
                "allowed_provider_profiles": [],
                "admin_only_model_selection": True,
                "retention_warning_acknowledged": True,
            },
            "cloud_fallback_warning_acknowledged": True,
        },
    )

    resp = await gov_client.patch(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
        json={
            "provider_security": {
                "local_only_mode": False,
                "cloud_fallback_allowed": True,
                "allowed_provider_profiles": [],
                "admin_only_model_selection": True,
                "retention_warning_acknowledged": True,
            },
            "cloud_fallback_warning_acknowledged": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["policy"]["provider_security"]["local_only_mode"] is False


@pytest.mark.asyncio
async def test_K_viewer_cannot_patch_governance(
    gov_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """K. Viewer role cannot write governance policy."""
    user, org = await _seed(db_session, role=OrganizationRole.viewer)
    tok = _token(user, org)

    resp = await gov_client.patch(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
        json={"provider_security": {"local_only_mode": True}},
    )
    assert resp.status_code in (403, 401)


@pytest.mark.asyncio
async def test_L_tenant_isolation_governance_independent_per_org(
    gov_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """L. Provider policy for org A does not affect org B."""
    user_a, org_a = await _seed(db_session)
    user_b, org_b = await _seed(db_session)
    tok_a = _token(user_a, org_a)
    tok_b = _token(user_b, org_b)

    # Set local_only_mode for org_a
    await gov_client.patch(
        "/api/v1/admin/governance",
        headers=_headers(token=tok_a, org_id=str(org_a.id)),
        json={
            "provider_security": {
                "local_only_mode": True,
                "cloud_fallback_allowed": False,
                "allowed_provider_profiles": ["local"],
                "admin_only_model_selection": True,
                "retention_warning_acknowledged": True,
            },
            "cloud_fallback_warning_acknowledged": True,
        },
    )

    # Org B should still have defaults
    resp_b = await gov_client.get(
        "/api/v1/admin/governance",
        headers=_headers(token=tok_b, org_id=str(org_b.id)),
    )
    ps_b = resp_b.json()["policy"]["provider_security"]
    assert ps_b["local_only_mode"] is False
    assert ps_b["cloud_fallback_allowed"] is True
    assert ps_b["allowed_provider_profiles"] == []


@pytest.mark.asyncio
async def test_O_audit_log_recorded_on_provider_security_update(
    gov_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """O. PATCH with changed provider_security records an audit log entry."""
    from sqlalchemy import select

    user, org = await _seed(db_session)
    tok = _token(user, org)

    await gov_client.patch(
        "/api/v1/admin/governance",
        headers=_headers(token=tok, org_id=str(org.id)),
        json={
            "provider_security": {
                "local_only_mode": True,
                "cloud_fallback_allowed": False,
                "allowed_provider_profiles": [],
                "admin_only_model_selection": True,
                "retention_warning_acknowledged": True,
            },
            "cloud_fallback_warning_acknowledged": True,
        },
    )

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.organization_id == org.id)
    )
    logs = result.scalars().all()
    assert len(logs) >= 1
    actions = [log.action for log in logs]
    # The governance PATCH endpoint records "admin.governance.policy.updated"
    assert any("governance" in a for a in actions)
