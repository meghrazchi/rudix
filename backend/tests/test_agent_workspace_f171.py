"""Tests for F171: list and cancel agent run endpoints."""

from __future__ import annotations

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
from app.domains.agents import AgentRunRepository
from app.main import app
from app.models.enums import AgentRunStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_repo = AgentRunRepository()


@pytest_asyncio.fixture
async def workspace_client(
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


async def _seed_org_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.member,
) -> tuple[User, Organization]:
    org = Organization(name=f"Workspace Org {uuid4().hex[:6]}", slug=f"ws-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"ws-user-{uuid4().hex[:8]}",
        email=f"ws-user-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


async def _seed_run(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    objective: str = "Test objective",
    status: str = AgentRunStatus.queued.value,
) -> str:
    run = await _repo.create_agent_run(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        objective=objective,
        status=status,
    )
    await db_session.commit()
    return str(run.id)


# ── list endpoint ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_agent_runs_returns_user_runs(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    for i in range(3):
        await _seed_run(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            objective=f"Objective {i}",
        )

    response = await workspace_client.get(
        "/api/v1/agent/runs",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert len(payload["runs"]) == 3
    assert all("run_id" in r for r in payload["runs"])
    assert all("status" in r for r in payload["runs"])


@pytest.mark.asyncio
async def test_list_agent_runs_is_org_scoped(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_org_user(db_session)
    user_b, org_b = await _seed_org_user(db_session)

    await _seed_run(db_session, organization_id=org_a.id, user_id=user_a.id)
    await _seed_run(db_session, organization_id=org_b.id, user_id=user_b.id)

    token_b = create_app_access_token(
        subject=user_b.external_auth_id,
        organization_id=str(org_b.id),
        expires_in_seconds=600,
    )
    response = await workspace_client.get(
        "/api/v1/agent/runs",
        headers=_headers(token=token_b, organization_id=str(org_b.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["runs"][0]["run_id"] != ""


@pytest.mark.asyncio
async def test_list_agent_runs_pagination(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    for i in range(5):
        await _seed_run(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            objective=f"Run {i}",
        )

    page1 = await workspace_client.get(
        "/api/v1/agent/runs?limit=2&offset=0",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert page1.status_code == 200
    p1 = page1.json()
    assert p1["total"] == 5
    assert len(p1["runs"]) == 2

    page2 = await workspace_client.get(
        "/api/v1/agent/runs?limit=2&offset=2",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert page2.status_code == 200
    p2 = page2.json()
    assert len(p2["runs"]) == 2
    ids1 = {r["run_id"] for r in p1["runs"]}
    ids2 = {r["run_id"] for r in p2["runs"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_list_agent_runs_empty_for_new_org(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await workspace_client.get(
        "/api/v1/agent/runs",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["runs"] == []


# ── cancel endpoint ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_queued_run(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        status=AgentRunStatus.queued.value,
    )

    response = await workspace_client.post(
        f"/api/v1/agent/runs/{run_id}/cancel",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "cancelled"
    assert payload["cancelled_at"] is not None


@pytest.mark.asyncio
async def test_cancel_running_run(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        status=AgentRunStatus.running.value,
    )

    response = await workspace_client.post(
        f"/api/v1/agent/runs/{run_id}/cancel",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_completed_run_returns_409(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        status=AgentRunStatus.completed.value,
    )

    response = await workspace_client.post(
        f"/api/v1/agent/runs/{run_id}/cancel",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "run_already_terminal"


@pytest.mark.asyncio
async def test_cancel_already_cancelled_run_returns_409(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        status=AgentRunStatus.cancelled.value,
    )

    response = await workspace_client.post(
        f"/api/v1/agent/runs/{run_id}/cancel",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_cancel_run_org_scoped(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_org_user(db_session)
    user_b, org_b = await _seed_org_user(db_session)

    run_id = await _seed_run(
        db_session,
        organization_id=org_a.id,
        user_id=user_a.id,
        status=AgentRunStatus.queued.value,
    )
    token_b = create_app_access_token(
        subject=user_b.external_auth_id,
        organization_id=str(org_b.id),
        expires_in_seconds=600,
    )

    response = await workspace_client.post(
        f"/api/v1/agent/runs/{run_id}/cancel",
        headers=_headers(token=token_b, organization_id=str(org_b.id)),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_nonexistent_run_returns_404(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    fake_id = str(uuid4())
    response = await workspace_client.post(
        f"/api/v1/agent/runs/{fake_id}/cancel",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_returns_full_detail_response(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        objective="Check compliance docs",
    )

    response = await workspace_client.post(
        f"/api/v1/agent/runs/{run_id}/cancel",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run_id
    assert payload["organization_id"] == str(org.id)
    assert payload["objective"] == "Check compliance docs"
    assert "steps" in payload
    assert "tool_calls" in payload
    assert "approvals" in payload


@pytest.mark.asyncio
async def test_cancel_requires_member_or_higher(
    workspace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.viewer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        status=AgentRunStatus.queued.value,
    )

    response = await workspace_client.post(
        f"/api/v1/agent/runs/{run_id}/cancel",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403
