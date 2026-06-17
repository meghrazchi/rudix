"""Tests for F174: agent run trace replay — trace timeline, redaction,
share tokens, retention policy CRUD, and restricted access security."""

from __future__ import annotations

import hashlib
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
from app.domains.agents.services.trace_service import (
    AgentTraceService,
    RetentionPolicySnapshot,
    build_trace_timeline,
)
from app.main import app
from app.models.agent import AgentTraceRetentionPolicy, AgentTraceShareToken
from app.models.enums import AgentRunStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_repo = AgentRunRepository()
_trace_service = AgentTraceService()


@pytest_asyncio.fixture
async def trace_client(
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
    org = Organization(name=f"Trace Org {uuid4().hex[:6]}", slug=f"tr-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"tr-user-{uuid4().hex[:8]}",
        email=f"tr-user-{uuid4().hex[:8]}@example.com",
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


async def _seed_run_with_steps(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    status: str = AgentRunStatus.completed.value,
    objective: str = "Summarise Q3 results",
) -> str:
    now = datetime.now(UTC)
    run = await _repo.create_agent_run(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        objective=objective,
        status=status,
    )
    await _repo.update_agent_run(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_id,
        started_at=now,
        completed_at=now + timedelta(seconds=5),
    )
    step = await _repo.create_agent_step(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_id,
        user_id=user_id,
        sequence=0,
        step_name="retrieve_documents",
        status="completed",
    )
    await _repo.update_agent_step(
        db_session,
        agent_step_id=step.id,
        organization_id=organization_id,
        agent_run_id=run.id,
        inputs={"query": "quarterly revenue", "prompt": "Find Q3 revenue figures"},
        outputs={"result_count": 3, "raw_content": "Revenue was $42M"},
        metrics={"retrieval_time_ms": 120},
        started_at=now,
        completed_at=now + timedelta(seconds=2),
        duration_ms=2000,
    )
    tc = await _repo.create_agent_tool_call(
        db_session,
        agent_run_id=run.id,
        agent_step_id=step.id,
        organization_id=organization_id,
        user_id=user_id,
        call_id=f"call-{uuid4().hex[:8]}",
        tool_name="search_documents",
        surface="api",
        effect_policy="read_only",
        attempt_number=1,
        arguments={"query": "Q3 revenue", "api_key": "sk-secret"},
        output={"hits": 3},
        status="succeeded",
    )
    await _repo.update_agent_tool_call(
        db_session,
        tool_call_id=tc.id,
        organization_id=organization_id,
        agent_run_id=run.id,
        latency_ms=80,
        input_size_bytes=50,
        output_size_bytes=120,
        started_at=now + timedelta(milliseconds=100),
        completed_at=now + timedelta(milliseconds=180),
    )
    await db_session.commit()
    return str(run.id)


# ── Unit tests for trace service ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retention_policy_defaults_when_none_set(
    db_session: AsyncSession,
) -> None:
    _, org = await _seed_org_user(db_session)
    policy = await _trace_service.get_retention_policy(db_session, org.id)
    assert policy.retain_days == 90
    assert not policy.redact_prompts
    assert not policy.redact_raw_content
    assert not policy.redact_tool_arguments
    assert not policy.is_any_redaction_active()


@pytest.mark.asyncio
async def test_upsert_retention_policy_creates_record(
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    updated = await _trace_service.upsert_retention_policy(
        db_session,
        organization_id=org.id,
        updated_by_user_id=user.id,
        retain_days=30,
        redact_prompts=True,
        redact_raw_content=True,
        redact_tool_arguments=False,
    )
    await db_session.commit()
    assert updated.retain_days == 30
    assert updated.redact_prompts is True

    # Subsequent call returns updated values
    policy = await _trace_service.get_retention_policy(db_session, org.id)
    assert policy.retain_days == 30
    assert policy.redact_prompts is True
    assert policy.is_any_redaction_active()


@pytest.mark.asyncio
async def test_upsert_retention_policy_updates_existing(
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    await _trace_service.upsert_retention_policy(
        db_session,
        organization_id=org.id,
        updated_by_user_id=user.id,
        retain_days=30,
        redact_prompts=True,
        redact_raw_content=False,
        redact_tool_arguments=False,
    )
    await db_session.commit()
    await _trace_service.upsert_retention_policy(
        db_session,
        organization_id=org.id,
        updated_by_user_id=user.id,
        retain_days=60,
        redact_prompts=False,
        redact_raw_content=True,
        redact_tool_arguments=True,
    )
    await db_session.commit()
    policy = await _trace_service.get_retention_policy(db_session, org.id)
    assert policy.retain_days == 60
    assert not policy.redact_prompts
    assert policy.redact_raw_content
    assert policy.redact_tool_arguments


def test_sensitive_key_redaction_in_tool_call_arguments() -> None:
    policy = RetentionPolicySnapshot(redact_tool_arguments=False)
    from app.domains.agents.services.trace_service import _redact_tool_call

    args, output = _redact_tool_call(
        {"query": "revenue", "api_key": "sk-secret-value", "token": "tok-abc"},
        {"hits": 3},
        policy,
    )
    assert args["query"] == "revenue"
    assert args["api_key"] == "[redacted]"
    assert args["token"] == "[redacted]"


def test_full_redact_tool_arguments_replaces_entirely() -> None:
    policy = RetentionPolicySnapshot(redact_tool_arguments=True)
    from app.domains.agents.services.trace_service import _redact_tool_call

    args, output = _redact_tool_call(
        {"query": "revenue", "top_k": 5},
        {"hits": 3},
        policy,
    )
    assert args == {"redacted": True}
    assert output == {"hits": 3}


def test_prompt_redaction_in_step_inputs() -> None:
    policy = RetentionPolicySnapshot(redact_prompts=True)
    from app.domains.agents.services.trace_service import _redact_step_inputs

    result = _redact_step_inputs(
        {"query": "Q3 revenue", "prompt": "Summarise this doc", "top_k": 5},
        policy,
    )
    assert result["query"] == "[redacted]"
    assert result["prompt"] == "[redacted]"
    assert result["top_k"] == 5


def test_raw_content_redaction_in_step_outputs() -> None:
    policy = RetentionPolicySnapshot(redact_raw_content=True)
    from app.domains.agents.services.trace_service import _redact_step_outputs

    result = _redact_step_outputs(
        {"result_count": 3, "raw_content": "Confidential text", "page_text": "Also secret"},
        policy,
    )
    assert result["result_count"] == 3
    assert result["raw_content"] == "[redacted]"
    assert result["page_text"] == "[redacted]"


# ── HTTP API tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_trace_returns_timeline(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run_with_steps(db_session, organization_id=org.id, user_id=user.id)

    resp = await trace_client.get(
        f"/api/v1/agent/runs/{run_id}/trace",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert isinstance(body["timeline"], list)
    assert body["total_events"] > 0
    event_types = {e["event_type"] for e in body["timeline"]}
    assert "run_started" in event_types
    assert body["step_count"] == 1
    assert body["tool_call_count"] == 1


@pytest.mark.asyncio
async def test_trace_sensitive_keys_always_redacted(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run_with_steps(db_session, organization_id=org.id, user_id=user.id)

    resp = await trace_client.get(
        f"/api/v1/agent/runs/{run_id}/trace",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    # api_key in tool call arguments must be redacted even without policy
    import json

    body_text = json.dumps(resp.json())
    assert "sk-secret" not in body_text


@pytest.mark.asyncio
async def test_trace_is_org_scoped(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_org_user(db_session)
    user_b, org_b = await _seed_org_user(db_session)
    run_id = await _seed_run_with_steps(
        db_session, organization_id=org_a.id, user_id=user_a.id
    )
    token_b = create_app_access_token(
        subject=user_b.external_auth_id,
        organization_id=str(org_b.id),
        expires_in_seconds=600,
    )

    resp = await trace_client.get(
        f"/api/v1/agent/runs/{run_id}/trace",
        headers=_headers(token=token_b, organization_id=str(org_b.id)),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_trace_metadata_is_fully_redacted(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run_with_steps(db_session, organization_id=org.id, user_id=user.id)

    resp = await trace_client.get(
        f"/api/v1/agent/runs/{run_id}/trace/export",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["export_safe"] is True
    assert "steps" in body
    assert "tool_calls" in body
    # raw content must not appear in export
    import json

    body_text = json.dumps(body)
    assert "Revenue was $42M" not in body_text
    assert "sk-secret" not in body_text


@pytest.mark.asyncio
async def test_share_trace_creates_token(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run_with_steps(db_session, organization_id=org.id, user_id=user.id)

    resp = await trace_client.post(
        f"/api/v1/agent/runs/{run_id}/trace/share",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"label": "Support ticket #123", "expires_in_hours": 24},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert body["label"] == "Support ticket #123"
    assert "expires_at" in body
    assert "token_id" in body


@pytest.mark.asyncio
async def test_shared_trace_accessible_without_auth(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    run_id = await _seed_run_with_steps(db_session, organization_id=org.id, user_id=user.id)

    # Directly create a share token
    run_uuid = UUID(run_id)
    share_token_obj, raw_token = await _trace_service.create_share_token(
        db_session,
        organization_id=org.id,
        run_id=run_uuid,
        created_by_user_id=user.id,
        label="test share",
        expires_in_hours=48,
    )
    await db_session.commit()

    resp = await trace_client.get(f"/api/v1/agent/traces/shared/{raw_token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["shared_via_token"] is True
    assert body["redacted"] is True


@pytest.mark.asyncio
async def test_shared_trace_invalid_token_returns_404(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    resp = await trace_client.get("/api/v1/agent/traces/shared/invalid-token-xyz")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "trace_not_found"


@pytest.mark.asyncio
async def test_shared_trace_expired_token_returns_404(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    run_id = await _seed_run_with_steps(db_session, organization_id=org.id, user_id=user.id)

    import secrets

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expired_token = AgentTraceShareToken(
        organization_id=org.id,
        agent_run_id=UUID(run_id),
        created_by_user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(expired_token)
    await db_session.commit()

    resp = await trace_client.get(f"/api/v1/agent/traces/shared/{raw_token}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_retention_policy_returns_defaults(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await trace_client.get(
        "/api/v1/admin/agent/trace-retention",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["retain_days"] == 90
    assert body["is_default"] is True
    assert not body["redact_prompts"]
    assert not body["redact_raw_content"]
    assert not body["redact_tool_arguments"]


@pytest.mark.asyncio
async def test_update_retention_policy(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await trace_client.patch(
        "/api/v1/admin/agent/trace-retention",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "retain_days": 30,
            "redact_prompts": True,
            "redact_raw_content": True,
            "redact_tool_arguments": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["retain_days"] == 30
    assert body["redact_prompts"] is True
    assert body["is_default"] is False


@pytest.mark.asyncio
async def test_trace_respects_retention_policy_redaction(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_user(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    run_id = await _seed_run_with_steps(db_session, organization_id=org.id, user_id=user.id)

    # Set redact_raw_content policy
    await _trace_service.upsert_retention_policy(
        db_session,
        organization_id=org.id,
        updated_by_user_id=user.id,
        retain_days=90,
        redact_prompts=False,
        redact_raw_content=True,
        redact_tool_arguments=False,
    )
    await db_session.commit()

    resp = await trace_client.get(
        f"/api/v1/agent/runs/{run_id}/trace",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["redacted"] is True
    import json

    body_text = json.dumps(body)
    assert "Revenue was $42M" not in body_text


@pytest.mark.asyncio
async def test_viewer_role_cannot_access_export(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    admin, org = await _seed_org_user(db_session, role=OrganizationRole.admin)
    viewer, _ = await _seed_org_user(db_session, role=OrganizationRole.viewer)
    # Add viewer to same org
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=viewer.id, role=OrganizationRole.viewer.value
        )
    )
    await db_session.commit()

    run_id = await _seed_run_with_steps(db_session, organization_id=org.id, user_id=admin.id)
    viewer_token = create_app_access_token(
        subject=viewer.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await trace_client.get(
        f"/api/v1/agent/runs/{run_id}/trace/export",
        headers=_headers(token=viewer_token, organization_id=str(org.id)),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_role_cannot_update_retention_policy(
    trace_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _, org = await _seed_org_user(db_session, role=OrganizationRole.admin)
    viewer = User(
        organization_id=org.id,
        external_auth_id=f"tr-viewer-{uuid4().hex[:8]}",
        email=f"tr-viewer-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(viewer)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=viewer.id, role=OrganizationRole.viewer.value
        )
    )
    await db_session.commit()

    viewer_token = create_app_access_token(
        subject=viewer.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp = await trace_client.patch(
        "/api/v1/admin/agent/trace-retention",
        headers=_headers(token=viewer_token, organization_id=str(org.id)),
        json={"retain_days": 7, "redact_prompts": True},
    )
    assert resp.status_code == 403
