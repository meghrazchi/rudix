"""Unauthenticated paths bind the tenant they resolved before touching strict tables (0.5.0).

The R04-08 known gaps closed in S3, each run as the non-owner probe role under ``strict``
with no tenant bound when the request starts:

- the shared agent trace page binds the share token's organisation before it loads the run;
- pre-authentication audit writes (login) bind the user's organisation before the insert;
- bot inbound events bind the installation's organisation before the mapping lookup, the
  audit rows, and the chat pipeline.

The trace test also runs with the binding replaced by a no-op, to show that the binding is
what makes the strict read work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.factory import get_auth_provider
from app.clients import qdrant_client as qdrant_module
from app.core.config import AuthProvider, RlsEnforcement, settings
from app.core.metrics import registry
from app.db.session import get_db_session
from app.interfaces.http import agent_runs as agent_runs_api
from app.interfaces.http import chat as chat_api
from app.main import app
from tests.conftest import RLS_PROBE_ROLE, RlsProbe
from tests.test_agent_trace_replay_f174 import _seed_org_user as _seed_trace_org_user
from tests.test_agent_trace_replay_f174 import _seed_run_with_steps, _trace_service
from tests.test_auth_api import _seed_principal
from tests.test_bots_api import (
    FakeQdrantClient,
    FakeQdrantResult,
    _inject_providers,
    _seed_document_with_chunk,
    _seed_installation_and_mapping,
    _sync_bot_headers,
)
from tests.test_bots_api import _seed_org_user as _seed_bot_org_user

pytestmark = pytest.mark.requires_postgres


@pytest_asyncio.fixture
async def probe_client(
    monkeypatch: pytest.MonkeyPatch, rls_probe_session: RlsProbe
) -> AsyncIterator[AsyncClient]:
    for name, value in {
        "auth_provider": AuthProvider.app,
        "app_auth_secret": SecretStr("test-secret"),
        "app_auth_issuer": "rudix-test",
        "app_auth_audience": "rudix-test-audience",
        "rate_limit_enabled": False,
        "feature_enable_agents": True,
        "feature_enable_collaboration_bots": True,
        "feature_enable_embeddings": True,
        "feature_enable_llm": True,
        "bot_slack_signing_secret": None,
        "bot_teams_shared_secret": None,
        "rls_enforcement": RlsEnforcement.strict,
    }.items():
        monkeypatch.setattr(settings, name, value)
    get_auth_provider.cache_clear()
    session = rls_probe_session.session

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()
    qdrant_module.qdrant_client = None
    chat_api._llm_service._provider = None
    chat_api._query_retrieval_service._embedding_provider = None
    get_auth_provider.cache_clear()


async def _become_unbound_probe(probe: RlsProbe) -> None:
    session = probe.session
    await session.execute(
        text(f"GRANT UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {RLS_PROBE_ROLE}")
    )
    await session.execute(
        text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {RLS_PROBE_ROLE}")
    )
    await probe.become_probe(organization_id=None, mode="strict")
    await session.commit()


async def _assert_ran_as_probe(probe: RlsProbe) -> None:
    row = (await probe.session.execute(text("SELECT current_user"))).one()
    assert row[0] == RLS_PROBE_ROLE


async def _owner_rows(probe: RlsProbe, sql: str, params: dict[str, Any]) -> list[Any]:
    await probe.become_owner()
    return list((await probe.session.execute(text(sql), params)).all())


def _bindings(path: str) -> float:
    value = registry.get_sample_value("rudix_rls_resolved_tenant_bindings_total", {"path": path})
    return float(value or 0.0)


async def _seed_shared_trace(probe: RlsProbe) -> tuple[str, str]:
    session = probe.session
    user, org = await _seed_trace_org_user(session)
    run_id = await _seed_run_with_steps(session, organization_id=org.id, user_id=user.id)
    _, raw_token = await _trace_service.create_share_token(
        session,
        organization_id=org.id,
        run_id=UUID(run_id),
        created_by_user_id=user.id,
        label="probe",
        expires_in_hours=1,
    )
    await session.commit()
    return run_id, raw_token


async def test_shared_agent_trace_binds_the_token_organisation(
    probe_client: AsyncClient, rls_probe_session: RlsProbe
) -> None:
    run_id, raw_token = await _seed_shared_trace(rls_probe_session)
    await _become_unbound_probe(rls_probe_session)
    before = _bindings("agent_trace_share")

    response = await probe_client.get(f"/api/v1/agent/traces/shared/{raw_token}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == run_id
    assert body["shared_via_token"] is True
    assert _bindings("agent_trace_share") == before + 1
    await _assert_ran_as_probe(rls_probe_session)


async def test_shared_agent_trace_without_binding_is_hidden_under_strict(
    probe_client: AsyncClient, rls_probe_session: RlsProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: with the binding removed, strict RLS hides the run from the trace page."""
    _, raw_token = await _seed_shared_trace(rls_probe_session)
    await _become_unbound_probe(rls_probe_session)

    async def _no_binding(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(agent_runs_api, "bind_resolved_tenant", _no_binding)
    response = await probe_client.get(f"/api/v1/agent/traces/shared/{raw_token}")

    assert response.status_code == 404
    await _assert_ran_as_probe(rls_probe_session)


async def test_login_audit_rows_are_written_under_strict(
    probe_client: AsyncClient, rls_probe_session: RlsProbe
) -> None:
    from app.models.enums import OrganizationRole

    user, org, _ = await _seed_principal(rls_probe_session.session, role=OrganizationRole.member)
    await _become_unbound_probe(rls_probe_session)
    before = _bindings("auth_audit")

    failed = await probe_client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"}
    )
    succeeded = await probe_client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )

    assert failed.status_code == 401
    assert succeeded.status_code == 200, succeeded.text
    assert _bindings("auth_audit") == before + 2
    await _assert_ran_as_probe(rls_probe_session)
    rows = await _owner_rows(
        rls_probe_session,
        "SELECT action, organization_id FROM audit_logs WHERE user_id = :user ORDER BY action",
        {"user": user.id},
    )
    assert [(row[0], row[1]) for row in rows] == [
        ("auth.login.failed", org.id),
        ("auth.login.succeeded", org.id),
    ]


async def test_bot_inbound_binds_the_installation_organisation(
    probe_client: AsyncClient, rls_probe_session: RlsProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = rls_probe_session.session
    org, _, member = await _seed_bot_org_user(session)
    document, chunk = await _seed_document_with_chunk(
        session,
        organization=org,
        uploader=member,
        filename="policy.pdf",
        text="Employees receive twenty days of annual leave.",
    )
    await _seed_installation_and_mapping(session, organization=org, user=member)
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.92,
                payload={
                    "organization_id": str(org.id),
                    "document_id": str(document.id),
                    "chunk_id": str(chunk.id),
                    "filename": "policy.pdf",
                    "page_number": 1,
                    "text": "Employees receive twenty days of annual leave.",
                },
            )
        ]
    )
    _inject_providers(
        monkeypatch,
        answer=(
            '{"answer":"Employees receive twenty days of annual leave.",'
            '"not_found":false,"citations":[]}'
        ),
    )
    await _become_unbound_probe(rls_probe_session)
    before = _bindings("bot_inbound")

    response = await probe_client.post(
        "/api/v1/bots/slack/events",
        headers=_sync_bot_headers(),
        json={
            "type": "event_callback",
            "team_id": "T-BOT",
            "event": {"user": "U-BOT", "channel": "C-BOT", "text": "How much leave?"},
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True, response.text
    assert _bindings("bot_inbound") == before + 1
    await _assert_ran_as_probe(rls_probe_session)
    actions = await _owner_rows(
        rls_probe_session,
        "SELECT action FROM audit_logs WHERE organization_id = :org AND action LIKE 'bots.ask.%'",
        {"org": org.id},
    )
    assert {row[0] for row in actions} == {"bots.ask.requested", "bots.ask.completed"}
    sessions = await _owner_rows(
        rls_probe_session,
        "SELECT organization_id FROM chat_sessions WHERE user_id = :user",
        {"user": member.id},
    )
    assert [row[0] for row in sessions] == [org.id]
