"""Tests for F173: agent tool policy and budget UI.

Covers:
- GET /admin/agent-policy returns resolved tool states and org budget
- PUT /admin/agent-policy/tools/{name} creates and updates overrides
- PUT with unknown tool name returns 422
- DELETE /admin/agent-policy/tools/{name} removes override
- DELETE non-existent override returns 404
- GET /admin/agent-policy/runs/{run_id}/effective-policy
- Role enforcement: viewer cannot access admin endpoints
- Policy snapshot stored on run record
- Budget enforcement: is_run_over_budget
- Tool enable/disable toggle
- Approval required override
- Required roles override
- Per-tool budget overrides resolve correctly
- Repository: upsert and delete round-trip
- Policy service: resolve_tool_state merges spec and override
- Policy service: check_tool_allowed honours allow list and override flag
"""

from __future__ import annotations

import os
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
from app.domains.agents.repositories.agent_policy import AgentToolPolicyRepository
from app.domains.agents.schemas.agent_policy import ToolPolicyUpsertRequest
from app.domains.agents.schemas.agent_tools import (
    ToolBudget,
    ToolEffectPolicy,
    ToolSpec,
    ToolSurface,
)
from app.domains.agents.services.policy_service import AgentPolicyService
from app.main import app
from app.models.agent import AgentRun
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_policy_repo = AgentToolPolicyRepository()


@pytest_asyncio.fixture
async def policy_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_agents", True)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def _seed_admin(
    db_session: AsyncSession,
    role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, Organization]:
    org = Organization(
        name=f"Policy Org {uuid4().hex[:6]}", slug=f"pol-org-{uuid4().hex[:8]}"
    )
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"pol-user-{uuid4().hex[:8]}",
        email=f"pol-user-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    member = OrganizationMember(
        organization_id=org.id, user_id=user.id, role=role.value
    )
    db_session.add(member)
    await db_session.flush()
    return user, org


def _token(user: User, org: Organization, role: OrganizationRole) -> str:
    return create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        roles=[role.value],
        secret=SecretStr("test-secret"),
        issuer="rudix-test",
        audience="rudix-test-audience",
    )


def _spec(name: str = "search.documents", *, approval_required: bool = False) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="Search through documents for relevant content",
        capability="document_search",
        effect_policy=ToolEffectPolicy.read_only,
        approval_required=approval_required,
        surfaces=[ToolSurface.api],
        budget=ToolBudget(
            max_calls_per_run=10,
            max_input_bytes=4096,
            max_output_bytes=8192,
            timeout_ms=5000,
            max_retry_attempts=2,
        ),
    )


# ── API tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_agent_policy_returns_resolved_tools(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = _token(user, org, OrganizationRole.admin)

    resp = await policy_client.get(
        "/admin/agent-policy", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "resolved_tools" in body
    assert "org_budget" in body
    assert isinstance(body["resolved_tools"], list)


@pytest.mark.asyncio
async def test_upsert_tool_policy_creates_override(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = _token(user, org, OrganizationRole.admin)

    # First fetch to get a valid tool name
    resp = await policy_client.get(
        "/admin/agent-policy", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    tools = resp.json()["resolved_tools"]
    if not tools:
        pytest.skip("No tools registered in catalog")

    tool_name = tools[0]["tool_name"]
    resp = await policy_client.put(
        f"/admin/agent-policy/tools/{tool_name}",
        json={"enabled": False, "approval_required": True, "max_calls_per_run": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["override"]["enabled"] is False
    assert body["override"]["approval_required"] is True
    assert body["override"]["max_calls_per_run"] == 5


@pytest.mark.asyncio
async def test_upsert_tool_policy_updates_existing(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = _token(user, org, OrganizationRole.admin)

    resp = await policy_client.get(
        "/admin/agent-policy", headers={"Authorization": f"Bearer {token}"}
    )
    tools = resp.json()["resolved_tools"]
    if not tools:
        pytest.skip("No tools registered in catalog")

    tool_name = tools[0]["tool_name"]
    # Create
    await policy_client.put(
        f"/admin/agent-policy/tools/{tool_name}",
        json={"enabled": True, "max_calls_per_run": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Update
    resp2 = await policy_client.put(
        f"/admin/agent-policy/tools/{tool_name}",
        json={"enabled": True, "max_calls_per_run": 7},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["override"]["max_calls_per_run"] == 7


@pytest.mark.asyncio
async def test_upsert_unknown_tool_returns_422(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = _token(user, org, OrganizationRole.admin)

    resp = await policy_client.put(
        "/admin/agent-policy/tools/not_a_real_tool_xyz",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_tool_policy_removes_override(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = _token(user, org, OrganizationRole.admin)

    resp = await policy_client.get(
        "/admin/agent-policy", headers={"Authorization": f"Bearer {token}"}
    )
    tools = resp.json()["resolved_tools"]
    if not tools:
        pytest.skip("No tools registered in catalog")

    tool_name = tools[0]["tool_name"]
    await policy_client.put(
        f"/admin/agent-policy/tools/{tool_name}",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    del_resp = await policy_client.delete(
        f"/admin/agent-policy/tools/{tool_name}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_nonexistent_override_returns_404(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = _token(user, org, OrganizationRole.admin)

    resp = await policy_client.get(
        "/admin/agent-policy", headers={"Authorization": f"Bearer {token}"}
    )
    tools = resp.json()["resolved_tools"]
    if not tools:
        pytest.skip("No tools registered in catalog")

    tool_name = tools[0]["tool_name"]
    resp = await policy_client.delete(
        f"/admin/agent-policy/tools/{tool_name}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_viewer_cannot_access_agent_policy(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session, role=OrganizationRole.viewer)
    token = _token(user, org, OrganizationRole.viewer)

    resp = await policy_client.get(
        "/admin/agent-policy", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_upsert_tool_policy(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session, role=OrganizationRole.viewer)
    token = _token(user, org, OrganizationRole.viewer)

    resp = await policy_client.put(
        "/admin/agent-policy/tools/some_tool",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_effective_policy_for_run_returns_snapshot(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = _token(user, org, OrganizationRole.admin)

    run = AgentRun(
        organization_id=org.id,
        user_id=user.id,
        status="completed",
        policy_snapshot_json={"recorded_at": "2026-06-19T10:00:00+00:00", "org_budget": {}},
    )
    db_session.add(run)
    await db_session.flush()

    resp = await policy_client.get(
        f"/admin/agent-policy/runs/{run.id}/effective-policy",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == str(run.id)
    assert "resolved_tools" in body


@pytest.mark.asyncio
async def test_effective_policy_run_not_found(
    policy_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = _token(user, org, OrganizationRole.admin)

    resp = await policy_client.get(
        f"/admin/agent-policy/runs/{uuid4()}/effective-policy",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── Unit tests for service and repository ─────────────────────────────────────


@pytest.mark.asyncio
async def test_repository_upsert_and_retrieve(db_session: AsyncSession) -> None:
    org = Organization(name=f"Repo Org {uuid4().hex[:6]}", slug=f"repo-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    override = await _policy_repo.upsert(
        db_session,
        organization_id=org.id,
        tool_name="search.documents",
        updated_by_user_id=None,
        enabled=False,
        approval_required=True,
        required_roles=["owner"],
        max_calls_per_run=5,
        max_input_bytes=None,
        max_output_bytes=None,
        timeout_ms=None,
        max_retry_attempts=None,
    )
    assert override.tool_name == "search.documents"
    assert override.enabled is False
    assert override.approval_required is True
    assert override.required_roles_json == ["owner"]
    assert override.max_calls_per_run == 5


@pytest.mark.asyncio
async def test_repository_upsert_updates_existing(db_session: AsyncSession) -> None:
    org = Organization(name=f"Repo2 Org {uuid4().hex[:6]}", slug=f"repo2-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    await _policy_repo.upsert(
        db_session,
        organization_id=org.id,
        tool_name="search.documents",
        updated_by_user_id=None,
        enabled=True,
        approval_required=False,
        required_roles=None,
        max_calls_per_run=3,
        max_input_bytes=None,
        max_output_bytes=None,
        timeout_ms=None,
        max_retry_attempts=None,
    )
    updated = await _policy_repo.upsert(
        db_session,
        organization_id=org.id,
        tool_name="search.documents",
        updated_by_user_id=None,
        enabled=False,
        approval_required=True,
        required_roles=["admin"],
        max_calls_per_run=10,
        max_input_bytes=None,
        max_output_bytes=None,
        timeout_ms=None,
        max_retry_attempts=None,
    )
    assert updated.enabled is False
    assert updated.max_calls_per_run == 10


@pytest.mark.asyncio
async def test_repository_delete(db_session: AsyncSession) -> None:
    org = Organization(name=f"Del Org {uuid4().hex[:6]}", slug=f"del-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    await _policy_repo.upsert(
        db_session,
        organization_id=org.id,
        tool_name="search.documents",
        updated_by_user_id=None,
        enabled=True,
        approval_required=None,
        required_roles=None,
        max_calls_per_run=None,
        max_input_bytes=None,
        max_output_bytes=None,
        timeout_ms=None,
        max_retry_attempts=None,
    )
    deleted = await _policy_repo.delete_by_tool(
        db_session, organization_id=org.id, tool_name="search.documents"
    )
    assert deleted is True

    none = await _policy_repo.get_by_tool(
        db_session, organization_id=org.id, tool_name="search.documents"
    )
    assert none is None


def test_policy_service_resolve_uses_spec_defaults() -> None:
    spec = _spec("search.documents")
    svc = AgentPolicyService(tool_specs=(spec,))
    state = svc._resolve_tool_state(spec, None)
    assert state.tool_name == "search.documents"
    assert state.enabled is True
    assert state.max_calls_per_run == spec.budget.max_calls_per_run
    assert state.is_overridden is False


def test_policy_service_resolve_applies_override() -> None:
    from app.models.agent_policy import AgentToolPolicyOverride
    from uuid import uuid4

    spec = _spec("search.documents")
    svc = AgentPolicyService(tool_specs=(spec,))

    override = AgentToolPolicyOverride(
        organization_id=uuid4(),
        tool_name="search.documents",
        enabled=False,
        approval_required=True,
        required_roles_json=["owner"],
        max_calls_per_run=3,
        max_input_bytes=None,
        max_output_bytes=None,
        timeout_ms=None,
        max_retry_attempts=None,
    )
    state = svc._resolve_tool_state(spec, override)
    assert state.enabled is False
    assert state.approval_required is True
    assert state.required_roles == ["owner"]
    assert state.max_calls_per_run == 3
    assert state.is_overridden is True


def test_policy_service_check_tool_allowed_with_empty_list() -> None:
    svc = AgentPolicyService(tool_specs=())
    assert svc.check_tool_allowed("search.documents", None, []) is True


def test_policy_service_check_tool_allowed_blocked_by_allowlist() -> None:
    svc = AgentPolicyService(tool_specs=())
    assert svc.check_tool_allowed("search.documents", None, ["create.note"]) is False


def test_policy_service_check_tool_disabled_by_override() -> None:
    from app.models.agent_policy import AgentToolPolicyOverride
    from uuid import uuid4

    svc = AgentPolicyService(tool_specs=())
    override = AgentToolPolicyOverride(
        organization_id=uuid4(),
        tool_name="search.documents",
        enabled=False,
        approval_required=None,
        required_roles_json=None,
        max_calls_per_run=None,
        max_input_bytes=None,
        max_output_bytes=None,
        timeout_ms=None,
        max_retry_attempts=None,
    )
    assert svc.check_tool_allowed("search.documents", override, []) is False


def test_policy_service_budget_not_exceeded() -> None:
    from app.models.agent import AgentRun

    run = AgentRun(
        organization_id=uuid4(),
        status="running",
        costs_json={"steps_taken": 3, "tool_calls_made": 5, "total_cost_usd": 0.001},
    )
    svc = AgentPolicyService(tool_specs=())
    exceeded, _ = svc.is_run_over_budget(
        run,
        org_max_steps=10,
        org_max_tool_calls=20,
        org_max_total_cost_usd=Decimal("1.00"),
    )
    assert exceeded is False


def test_policy_service_budget_steps_exceeded() -> None:
    from app.models.agent import AgentRun

    run = AgentRun(
        organization_id=uuid4(),
        status="running",
        max_steps=5,
        costs_json={"steps_taken": 5, "tool_calls_made": 0, "total_cost_usd": 0},
    )
    svc = AgentPolicyService(tool_specs=())
    exceeded, reason = svc.is_run_over_budget(
        run,
        org_max_steps=10,
        org_max_tool_calls=None,
        org_max_total_cost_usd=None,
    )
    assert exceeded is True
    assert "steps" in reason
