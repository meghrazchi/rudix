"""Tests for F172: agent human approval queue — org-wide listing, decision
state transitions (approved / rejected / changes_requested), expiry, and
role-based access control."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
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
from app.models.enums import AgentApprovalStatus, AgentRunStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_repo = AgentRunRepository()


@pytest_asyncio.fixture
async def approval_client(
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
    role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, Organization]:
    org = Organization(name=f"Approval Org {uuid4().hex[:6]}", slug=f"ap-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"ap-user-{uuid4().hex[:8]}",
        email=f"ap-user-{uuid4().hex[:8]}@example.com",
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


async def _seed_run_with_approval(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    run_status: str = AgentRunStatus.waiting_approval.value,
    approval_status: str = AgentApprovalStatus.pending.value,
    expires_at: datetime | None = None,
    request_payload: dict | None = None,
    objective: str = "Test agentic task",
) -> tuple[str, str]:
    run = await _repo.create_agent_run(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        objective=objective,
        status=run_status,
    )
    approval = await _repo.create_agent_approval(
        db_session,
        organization_id=organization_id,
        agent_run_id=run.id,
        requested_by_user_id=user_id,
        status=approval_status,
        request_summary="Tool wants to write a file",
        request_payload=request_payload or {"tool_name": "file_write", "risk_level": "high"},
        expires_at=expires_at,
    )
    await db_session.commit()
    return str(run.id), str(approval.id)


# ── GET /agent/approvals ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_approval_queue_returns_pending(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    await _seed_run_with_approval(db_session, organization_id=org.id, user_id=user.id)

    response = await approval_client.get(
        "/api/v1/agent/approvals",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["approvals"]) == 1
    item = body["approvals"][0]
    assert item["status"] == "pending"
    assert item["risk_level"] == "high"
    assert item["tool_name"] == "file_write"
    assert item["request_summary"] == "Tool wants to write a file"
    assert item["run_objective"] == "Test agentic task"
    assert "agent_run_id" in item
    assert "approval_id" in item


@pytest.mark.asyncio
async def test_list_approval_queue_is_org_scoped(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_org_user(db_session)
    user_b, org_b = await _seed_org_user(db_session)

    await _seed_run_with_approval(db_session, organization_id=org_a.id, user_id=user_a.id)

    token_b = create_app_access_token(
        subject=user_b.external_auth_id,
        organization_id=str(org_b.id),
        expires_in_seconds=600,
    )
    response = await approval_client.get(
        "/api/v1/agent/approvals",
        headers=_headers(token=token_b, organization_id=str(org_b.id)),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_approval_queue_status_filter(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id,
        approval_status=AgentApprovalStatus.pending.value,
    )
    await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id,
        approval_status=AgentApprovalStatus.approved.value,
    )

    response = await approval_client.get(
        "/api/v1/agent/approvals?status_filter=pending",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["approvals"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_list_approval_queue_pagination(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    for _ in range(5):
        await _seed_run_with_approval(db_session, organization_id=org.id, user_id=user.id)

    page1 = await approval_client.get(
        "/api/v1/agent/approvals?limit=2&offset=0",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    page2 = await approval_client.get(
        "/api/v1/agent/approvals?limit=2&offset=2",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert page1.status_code == page2.status_code == 200
    assert page1.json()["total"] == 5
    ids1 = {a["approval_id"] for a in page1.json()["approvals"]}
    ids2 = {a["approval_id"] for a in page2.json()["approvals"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_list_approval_queue_requires_admin_or_owner(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await approval_client.get(
        "/api/v1/agent/approvals",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ── Decision: approve ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_approve_transitions_to_approved(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id
    )

    response = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "approved", "reason": "Looks safe"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["decision_reason"] == "Looks safe"
    assert body["decided_by_user_id"] == str(user.id)
    assert body["decided_at"] is not None
    assert body["agent_run_id"] == run_id


@pytest.mark.asyncio
async def test_decision_reject_transitions_to_rejected(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id
    )

    response = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "rejected", "reason": "Too risky"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["decision_reason"] == "Too risky"


# ── Decision: changes_requested ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_changes_requested_transitions_correctly(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id
    )

    response = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "changes_requested", "reason": "Narrow the file path first"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "changes_requested"
    assert body["decision_reason"] == "Narrow the file path first"
    assert body["decided_by_user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_decision_changes_requested_then_approve(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id
    )

    # First request changes
    r1 = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "changes_requested", "reason": "Adjust scope"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "changes_requested"

    # Then approve
    r2 = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "approved", "reason": "Scope looks good now"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_decision_invalid_status_rejected(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id
    )

    response = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "cancelled"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_decision_already_approved_returns_409(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id,
        approval_status=AgentApprovalStatus.approved.value,
    )

    response = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "approved"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "approval_not_actionable"


@pytest.mark.asyncio
async def test_decision_requires_admin_or_owner(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id
    )

    response = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "approved"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ── Expiry handling ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_on_expired_approval_returns_409(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    past = datetime.now(tz=UTC) - timedelta(seconds=1)
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id,
        expires_at=past,
    )

    response = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "approved"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "approval_expired"


@pytest.mark.asyncio
async def test_expire_pending_approvals_repository_method(
    db_session: AsyncSession,
) -> None:
    _, org_a = await _seed_org_user(db_session)
    _, org_b = await _seed_org_user(db_session)

    # Seed approvals: 2 expired in org_a, 1 future in org_a, 1 expired in org_b
    past = datetime.now(tz=UTC) - timedelta(minutes=5)
    future = datetime.now(tz=UTC) + timedelta(hours=1)

    run_a1 = await _repo.create_agent_run(
        db_session, organization_id=org_a.id, user_id=None, status="waiting_approval"
    )
    run_a2 = await _repo.create_agent_run(
        db_session, organization_id=org_a.id, user_id=None, status="waiting_approval"
    )
    run_a3 = await _repo.create_agent_run(
        db_session, organization_id=org_a.id, user_id=None, status="waiting_approval"
    )
    run_b1 = await _repo.create_agent_run(
        db_session, organization_id=org_b.id, user_id=None, status="waiting_approval"
    )

    for run, org, exp in [
        (run_a1, org_a, past),
        (run_a2, org_a, past),
        (run_a3, org_a, future),
        (run_b1, org_b, past),
    ]:
        await _repo.create_agent_approval(
            db_session,
            organization_id=org.id,
            agent_run_id=run.id,
            status="pending",
            expires_at=exp,
        )
    await db_session.flush()

    expired_count = await _repo.expire_pending_approvals(db_session)
    await db_session.flush()

    assert expired_count == 3  # 2 in org_a + 1 in org_b

    # Org-scoped expiry
    run_a4 = await _repo.create_agent_run(
        db_session, organization_id=org_a.id, user_id=None, status="waiting_approval"
    )
    run_b2 = await _repo.create_agent_run(
        db_session, organization_id=org_b.id, user_id=None, status="waiting_approval"
    )
    for run, org in [(run_a4, org_a), (run_b2, org_b)]:
        await _repo.create_agent_approval(
            db_session,
            organization_id=org.id,
            agent_run_id=run.id,
            status="pending",
            expires_at=past,
        )
    await db_session.flush()

    scoped_count = await _repo.expire_pending_approvals(db_session, organization_id=org_a.id)
    assert scoped_count == 1


# ── Audit trace ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_decision_appears_in_run_approvals(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id
    )

    await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "rejected", "reason": "Not authorised"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    detail = await approval_client.get(
        f"/api/v1/agent/runs/{run_id}",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert detail.status_code == 200
    approvals = detail.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["status"] == "rejected"
    assert approvals[0]["decision_reason"] == "Not authorised"
    assert approvals[0]["decided_by_user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_approval_response_includes_agent_run_id(
    approval_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id, approval_id = await _seed_run_with_approval(
        db_session, organization_id=org.id, user_id=user.id
    )

    response = await approval_client.post(
        f"/api/v1/agent/runs/{run_id}/approvals/{approval_id}/decision",
        json={"status": "approved"},
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["agent_run_id"] == run_id
