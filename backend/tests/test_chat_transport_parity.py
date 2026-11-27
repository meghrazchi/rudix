"""R02-01: HTTP POST /chat and the /chat/ws pipeline enforce the same quota, usage and
cite-access rules for the same question."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import (
    FakeQdrantClient,
    FakeQdrantResult,
    _auth_headers,
    _FakeWebSocket,
    _inject_providers,
    _seed_document_with_chunk,
    _seed_principal,
    _seed_quota_policy,
    chat_query_client,  # noqa: F401  (pytest fixture re-export)
)

from app.auth.token_codec import create_app_access_token
from app.clients import qdrant_client as qdrant_module
from app.interfaces.http import chat as chat_api
from app.models.authorization import ResourceAccessDeny
from app.models.chat import ChatMessage
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.quotas import OrgQuotaUsage
from app.models.user import User

pytestmark = [pytest.mark.isolation, pytest.mark.asyncio, pytest.mark.both_dialects]

TRANSPORTS = ("http", "ws")
QUESTION = "How much annual leave is provided?"
TEXT_A = "Employees receive twenty days of annual leave."
TEXT_B = "Confidential: executives receive forty days of annual leave."
ANSWER = (
    '{"answer":"Employees receive twenty days of annual leave.","not_found":false,"citations":[]}'
)


class _SessionLocalOverride:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> object:
        session = self._session

        class _SessionContext:
            async def __aenter__(self_inner) -> AsyncSession:
                return session

            async def __aexit__(self_inner, exc_type: object, exc: object, tb: object) -> bool:
                return False

        return _SessionContext()


async def _ask(
    transport: str,
    *,
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    user: User,
    organization: Organization,
    role: OrganizationRole,
) -> dict[str, Any]:
    """Ask QUESTION over one transport; return a normalised outcome."""
    if transport == "http":
        token = create_app_access_token(
            subject=user.external_auth_id,
            organization_id=str(organization.id),
            expires_in_seconds=600,
        )
        response = await client.post(
            "/api/v1/chat",
            headers=_auth_headers(token=token, organization_id=str(organization.id)),
            json={"question": QUESTION, "top_k": 3, "rerank": False},
        )
        body = response.json()
        if response.status_code != 200:
            return {"error_code": body["detail"]["code"], "status": response.status_code}
        return {"error_code": None, "citations": body["citations"]}

    monkeypatch.setattr(chat_api, "SessionLocal", _SessionLocalOverride(db_session))
    websocket = _FakeWebSocket()
    principal = chat_api.AuthenticatedPrincipal(
        user_id=str(user.id),
        organization_id=str(organization.id),
        email=user.email,
        roles=[role.value],
        auth_provider="app",
    )
    await chat_api._run_ws_chat_pipeline(
        websocket=websocket,  # type: ignore[arg-type]
        payload={"question": QUESTION, "top_k": 3, "rerank": False, "chat_session_id": None},
        principal=principal,
        request_id=f"ws-parity-{role.value}",
        sequence_start=0,
    )
    events = [json.loads(text) for text in websocket.sent_texts]
    last = events[-1]
    if last["event"] == "chat.error":
        return {"error_code": last["safe_error_code"], "payload": last["payload"], "events": events}
    assert last["event"] == "chat.completed", events
    return {"error_code": None, "citations": last["payload"]["response"]["citations"]}


async def _question_usage(db_session: AsyncSession, organization_id: UUID) -> int:
    value = await db_session.scalar(
        select(OrgQuotaUsage.current_value).where(
            OrgQuotaUsage.organization_id == organization_id,
            OrgQuotaUsage.quota_type == "questions",
        )
    )
    return int(value or 0)


async def _seed_two_documents(
    db_session: AsyncSession, *, organization: Organization, user: User
) -> tuple[Any, Any]:
    doc_a, chunk_a = await _seed_document_with_chunk(
        db_session, organization=organization, uploader=user, filename="a.pdf", text=TEXT_A
    )
    doc_b, chunk_b = await _seed_document_with_chunk(
        db_session, organization=organization, uploader=user, filename="b.pdf", text=TEXT_B
    )
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.93,
                payload={
                    "organization_id": str(organization.id),
                    "document_id": str(doc_b.id),  # type: ignore[attr-defined]
                    "chunk_id": str(chunk_b.id),
                    "filename": "b.pdf",
                    "page_number": 1,
                    "text": TEXT_B,
                },
            ),
            FakeQdrantResult(
                score=0.92,
                payload={
                    "organization_id": str(organization.id),
                    "document_id": str(doc_a.id),  # type: ignore[attr-defined]
                    "chunk_id": str(chunk_a.id),
                    "filename": "a.pdf",
                    "page_number": 1,
                    "text": TEXT_A,
                },
            ),
        ]
    )
    return doc_a, doc_b


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_over_quota_question_is_refused_with_plan_limit_exceeded(
    transport: str,
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    await _seed_quota_policy(
        db_session,
        organization_id=organization.id,
        limits={"questions": {"soft_limit": 0, "hard_limit": 0, "reset_window": "per_day"}},
    )
    _inject_providers(monkeypatch, answer=ANSWER)

    outcome = await _ask(
        transport,
        client=chat_query_client,
        db_session=db_session,
        monkeypatch=monkeypatch,
        user=user,
        organization=organization,
        role=OrganizationRole.member,
    )

    assert outcome["error_code"] == "plan_limit_exceeded"
    if transport == "http":
        assert outcome["status"] == 403
    else:
        assert set(outcome["payload"]) == {"quota_type", "retryable", "next_reset_at"}
        assert outcome["payload"]["quota_type"] == "questions"
        assert outcome["payload"]["retryable"] is True
        step_states = [
            (e["payload"]["step_key"], e["payload"]["state"])
            for e in outcome["events"]
            if e["event"] == "activity.step.update"
        ]
        assert ("understanding_question", "failed") in step_states
    message_count = await db_session.scalar(select(func.count()).select_from(ChatMessage))
    assert message_count == 0
    assert await _question_usage(db_session, organization.id) == 0


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_successful_question_increments_question_usage_by_one(
    transport: str,
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    await _seed_two_documents(db_session, organization=organization, user=user)
    _inject_providers(monkeypatch, answer=ANSWER)
    before = await _question_usage(db_session, organization.id)

    outcome = await _ask(
        transport,
        client=chat_query_client,
        db_session=db_session,
        monkeypatch=monkeypatch,
        user=user,
        organization=organization,
        role=OrganizationRole.member,
    )

    assert outcome["error_code"] is None
    assert await _question_usage(db_session, organization.id) == before + 1


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize(
    ("role", "expected_files"),
    [
        (OrganizationRole.member, {"a.pdf"}),
        (OrganizationRole.admin, {"a.pdf", "b.pdf"}),
    ],
)
async def test_cite_deny_removes_document_from_citations_on_both_transports(
    transport: str,
    role: OrganizationRole,
    expected_files: set[str],
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, organization, _ = await _seed_principal(db_session, role=role)
    _doc_a, doc_b = await _seed_two_documents(db_session, organization=organization, user=user)
    db_session.add(
        ResourceAccessDeny(
            organization_id=organization.id,
            user_id=user.id,
            principal_type="user",
            principal_value=str(user.id),
            resource_type="document",
            resource_id=str(doc_b.id),
            action="cite",
            status="active",
        )
    )
    await db_session.commit()
    chat_provider, _ = _inject_providers(monkeypatch, answer=ANSWER)

    outcome = await _ask(
        transport,
        client=chat_query_client,
        db_session=db_session,
        monkeypatch=monkeypatch,
        user=user,
        organization=organization,
        role=role,
    )

    assert outcome["error_code"] is None
    cited_files = {citation["filename"] for citation in outcome["citations"]}
    assert cited_files == expected_files
    if role == OrganizationRole.member:
        prompts = [call.prompt for call in chat_provider.calls]
        assert prompts, "expected the LLM to be called"
        assert all(TEXT_B not in prompt for prompt in prompts)


async def test_ws_non_quota_check_error_falls_through_to_internal_error(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    user, organization, _ = await _seed_principal(db_session)
    _inject_providers(monkeypatch, answer=ANSWER)

    async def _broken_quota(*_args: object, **_kwargs: object) -> None:
        raise HTTPException(status_code=500, detail="quota store unavailable")

    monkeypatch.setattr(chat_api, "ensure_chat_quota", _broken_quota)

    outcome = await _ask(
        "ws",
        client=chat_query_client,
        db_session=db_session,
        monkeypatch=monkeypatch,
        user=user,
        organization=organization,
        role=OrganizationRole.member,
    )

    assert outcome["error_code"] == "internal_error"
    assert outcome["payload"] is None
    message_count = await db_session.scalar(select(func.count()).select_from(ChatMessage))
    assert message_count == 0
