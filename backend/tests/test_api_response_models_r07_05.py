"""R07-05: response models for four endpoints the frontend consumes.

The routes used ``response_model=dict`` (or none). These tests pin the JSON produced
before the models were added: same keys, same values, no key added or dropped, and the
organisation and visibility behaviour unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.agents import AgentRunRepository
from app.domains.agents.services.trace_service import AgentTraceService
from app.domains.metadata.repositories.metadata import MetadataFieldRepository
from app.domains.metadata.services.metadata_service import MetadataService
from app.interfaces.http import agent_runs as agent_runs_module
from app.main import app
from app.models.document import Document
from app.models.enums import AgentRunStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_repo = AgentRunRepository()
_trace_service = AgentTraceService()

# Keys of AgentTraceService.build_trace, captured before the response model existed.
TRACE_KEYS = {
    "run_id",
    "organization_id",
    "status",
    "objective",
    "surface",
    "started_at",
    "completed_at",
    "cancelled_at",
    "created_at",
    "total_cost_usd",
    "error_message",
    "trace_request_id",
    "redacted",
    "timeline",
    "total_events",
    "step_count",
    "tool_call_count",
    "approval_count",
    "policy_snapshot",
}


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> AsyncClient:
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
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        yield http_client
    app.dependency_overrides.clear()


async def _seed(db_session: AsyncSession) -> tuple[User, Organization, dict[str, str]]:
    org = Organization(name=f"R05 Org {uuid4().hex[:6]}", slug=f"r05-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"r05-{uuid4().hex[:8]}",
        email=f"r05-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=OrganizationRole.admin.value
        )
    )
    await db_session.commit()
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}
    return user, org, headers


async def _seed_run(db_session: AsyncSession, org: Organization, user: User) -> str:
    now = datetime.now(UTC)
    run = await _repo.create_agent_run(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        objective="Summarise Q3 results",
        status=AgentRunStatus.completed.value,
    )
    await _repo.update_agent_run(
        db_session,
        agent_run_id=run.id,
        organization_id=org.id,
        started_at=now,
        completed_at=now + timedelta(seconds=5),
    )
    step = await _repo.create_agent_step(
        db_session,
        agent_run_id=run.id,
        organization_id=org.id,
        user_id=user.id,
        sequence=0,
        step_name="retrieve_documents",
        status="completed",
    )
    await _repo.update_agent_step(
        db_session,
        agent_step_id=step.id,
        organization_id=org.id,
        agent_run_id=run.id,
        inputs={"query": "revenue"},
        outputs={"result_count": 3},
        started_at=now,
        completed_at=now + timedelta(seconds=2),
        duration_ms=2000,
    )
    await db_session.commit()
    return str(run.id)


# ── GET /agent/runs/{run_id}/trace ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trace_json_keys_unchanged(client: AsyncClient, db_session: AsyncSession) -> None:
    user, org, headers = await _seed(db_session)
    run_id = await _seed_run(db_session, org, user)

    resp = await client.get(f"/api/v1/agent/runs/{run_id}/trace", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == TRACE_KEYS  # shared_via_token is not added to the authenticated trace
    assert body["run_id"] == run_id
    assert body["organization_id"] == str(org.id)
    assert body["step_count"] == 1
    assert body["total_events"] == len(body["timeline"])
    for event in body["timeline"]:
        assert {"event_type", "run_id", "timestamp", "data"} <= set(event)
        assert set(event) <= {
            "event_type",
            "run_id",
            "step_id",
            "tool_call_id",
            "approval_id",
            "timestamp",
            "data",
        }
    started = next(e for e in body["timeline"] if e["event_type"] == "run_started")
    assert "step_id" not in started  # optional keys the service omits stay omitted
    step_event = next(e for e in body["timeline"] if e["event_type"] == "step_started")
    assert step_event["step_id"]


@pytest.mark.asyncio
async def test_trace_equals_service_output(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The response body equals the dict the service returns, value for value."""
    user, org, headers = await _seed(db_session)
    run_id = await _seed_run(db_session, org, user)
    captured: dict[str, Any] = {}
    original = agent_runs_module.agent_trace_service.build_trace

    def _capture(run: Any, policy: Any) -> dict[str, Any]:
        result = original(run, policy)
        captured.update(result)
        return result

    monkeypatch.setattr(agent_runs_module.agent_trace_service, "build_trace", _capture)

    resp = await client.get(f"/api/v1/agent/runs/{run_id}/trace", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == captured


@pytest.mark.asyncio
async def test_trace_open_dicts_pass_through(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, headers = await _seed(db_session)
    run_id = await _seed_run(db_session, org, user)
    payload: dict[str, Any] = {key: None for key in TRACE_KEYS}
    payload.update(
        run_id=run_id,
        organization_id=str(org.id),
        status="completed",
        surface="api",
        created_at="2026-01-01T00:00:00+00:00",
        redacted=False,
        total_events=1,
        step_count=0,
        tool_call_count=0,
        approval_count=0,
        policy_snapshot={"nested": {"a": [1, 2]}, "flag": True},
        timeline=[
            {
                "event_type": "tool_called",
                "run_id": run_id,
                "step_id": None,
                "tool_call_id": "tc-1",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "data": {"arguments": {"q": "x", "n": [1, {"k": None}]}},
            }
        ],
    )
    monkeypatch.setattr(
        agent_runs_module.agent_trace_service, "build_trace", lambda run, policy: dict(payload)
    )

    resp = await client.get(f"/api/v1/agent/runs/{run_id}/trace", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == payload


@pytest.mark.asyncio
async def test_trace_cross_org_is_404(client: AsyncClient, db_session: AsyncSession) -> None:
    user, org, _ = await _seed(db_session)
    run_id = await _seed_run(db_session, org, user)
    _, _, other_headers = await _seed(db_session)

    resp = await client.get(f"/api/v1/agent/runs/{run_id}/trace", headers=other_headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Agent run not found"


# ── GET /agent/traces/shared/{token} ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_shared_trace_keeps_shared_flag_and_redaction(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org, _ = await _seed(db_session)
    run_id = await _seed_run(db_session, org, user)
    _, raw_token = await _trace_service.create_share_token(
        db_session,
        organization_id=org.id,
        run_id=UUID(run_id),
        created_by_user_id=user.id,
        label="r05",
        expires_in_hours=48,
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/agent/traces/shared/{raw_token}")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == TRACE_KEYS | {"shared_via_token"}
    assert body["shared_via_token"] is True
    assert body["redacted"] is True
    assert body["run_id"] == run_id


@pytest.mark.asyncio
async def test_shared_trace_unknown_token_error_shape_unchanged(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/agent/traces/shared/not-a-token")

    assert resp.status_code == 404
    assert resp.json()["detail"] == {
        "code": "trace_not_found",
        "message": "Trace share link is invalid or expired.",
    }


# ── GET /admin/metadata/filter-documents ──────────────────────────────────────


async def _seed_filter_data(
    db_session: AsyncSession, org: Organization
) -> tuple[Document, Document, str]:
    field = await MetadataFieldRepository().create(
        db_session,
        organization_id=org.id,
        name="region",
        display_name="Region",
        field_type="select",
        allowed_values=["EMEA", "APAC"],
        is_required=False,
        is_filterable=True,
        description=None,
        sort_order=0,
    )
    docs = []
    for name, value in (("a.pdf", "EMEA"), ("b.pdf", "APAC")):
        doc = Document(
            organization_id=org.id,
            filename=name,
            file_type="pdf",
            status="indexed",
            file_size_bytes=1,
        )
        db_session.add(doc)
        await db_session.flush()
        await MetadataService().validate_and_save_document_values(
            db_session,
            document_id=doc.id,
            organization_id=org.id,
            values=[{"field_id": str(field.id), "value": value}],
            changed_by_id=None,
        )
        docs.append(doc)
    await db_session.commit()
    return docs[0], docs[1], str(field.id)


@pytest.mark.asyncio
async def test_filter_documents_json_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org, headers = await _seed(db_session)
    doc_a, _doc_b, field_id = await _seed_filter_data(db_session, org)

    resp = await client.get(
        "/api/v1/admin/metadata/filter-documents",
        params={"filter": f"{field_id}:EMEA"},
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"document_ids": [str(doc_a.id)]}


@pytest.mark.asyncio
async def test_filter_documents_without_filters_is_empty(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, headers = await _seed(db_session)

    resp = await client.get("/api/v1/admin/metadata/filter-documents", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"document_ids": []}


@pytest.mark.asyncio
async def test_filter_documents_rejects_malformed_filter(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, headers = await _seed(db_session)

    resp = await client.get(
        "/api/v1/admin/metadata/filter-documents", params={"filter": "nocolon"}, headers=headers
    )

    assert resp.status_code == 422
    assert "Invalid filter format" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_filter_documents_is_org_scoped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org, _ = await _seed(db_session)
    _, _, field_id = await _seed_filter_data(db_session, org)
    _, _, other_headers = await _seed(db_session)

    resp = await client.get(
        "/api/v1/admin/metadata/filter-documents",
        params={"filter": f"{field_id}:EMEA"},
        headers=other_headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"document_ids": []}


# ── POST /security/sessions/revoke-all ────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_all_sessions_json_unchanged(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, headers = await _seed(db_session)

    resp = await client.post("/api/v1/security/sessions/revoke-all", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"revoked_count": 0}


@pytest.mark.asyncio
async def test_revoke_all_sessions_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/security/sessions/revoke-all")

    assert resp.status_code == 401
