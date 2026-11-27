"""D1: scope-inventory answers obey the cite permission on both transports.

A reader who may see document B in the listing but not cite it gets B listed
with no citation for B. Owners and admins bypass the cite check.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import (
    _auth_headers,
    _FakeWebSocket,
    _inject_providers,
    _seed_document_with_chunk,
    _seed_principal,
    chat_query_client,  # noqa: F401  (pytest fixture re-export)
)
from test_chat_transport_parity import TRANSPORTS, _SessionLocalOverride

from app.application.chat import citation_access
from app.auth.policy_engine import Action
from app.auth.token_codec import create_app_access_token
from app.interfaces.http import chat as chat_api
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.user import User

pytestmark = [pytest.mark.isolation, pytest.mark.asyncio]

INVENTORY_QUESTION = "Which files are included in this scope?"


def _deny_cite_only(monkeypatch: pytest.MonkeyPatch, document_id: str) -> None:
    """Allow reading/chatting with the document but refuse Action.cite for it.

    Explicit deny rows are action-agnostic (they also block chat and so the
    listing), so the cite-only decision is simulated at the policy boundary
    used by ``filter_chunks_by_cite_access``.
    """
    service = citation_access._authorization_service
    original = service.filter_accessible_resources

    async def _filter(
        principal: Any, action: Action, contexts: Any, db_session: AsyncSession
    ) -> Any:
        allowed = await original(principal, action, contexts, db_session)
        if action == Action.cite:
            return [ctx for ctx in allowed if ctx.resource_id != document_id]
        return allowed

    monkeypatch.setattr(service, "filter_accessible_resources", _filter)


async def _ask_inventory(
    transport: str,
    *,
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    user: User,
    organization: Organization,
    role: OrganizationRole,
) -> dict[str, Any]:
    if transport == "http":
        token = create_app_access_token(
            subject=user.external_auth_id,
            organization_id=str(organization.id),
            expires_in_seconds=600,
        )
        response = await client.post(
            "/api/v1/chat",
            headers=_auth_headers(token=token, organization_id=str(organization.id)),
            json={"question": INVENTORY_QUESTION, "top_k": 3, "rerank": False},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        return {"answer": body["answer"], "citations": body["citations"]}

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
        payload={
            "question": INVENTORY_QUESTION,
            "top_k": 3,
            "rerank": False,
            "chat_session_id": None,
        },
        principal=principal,
        request_id=f"ws-inventory-{role.value}",
        sequence_start=0,
    )
    last = [json.loads(text) for text in websocket.sent_texts][-1]
    assert last["event"] == "chat.completed", last
    response_payload = last["payload"]["response"]
    return {"answer": response_payload["answer"], "citations": response_payload["citations"]}


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize(
    ("role", "expected_cited"),
    [
        (OrganizationRole.member, {"a.pdf"}),
        (OrganizationRole.admin, {"a.pdf", "b.pdf"}),
    ],
)
async def test_scope_inventory_citations_obey_cite_permission(
    transport: str,
    role: OrganizationRole,
    expected_cited: set[str],
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, organization, _ = await _seed_principal(db_session, role=role)
    await _seed_document_with_chunk(
        db_session, organization=organization, uploader=user, filename="a.pdf", text="Alpha text."
    )
    doc_b, _chunk_b = await _seed_document_with_chunk(
        db_session, organization=organization, uploader=user, filename="b.pdf", text="Beta text."
    )
    await db_session.commit()
    _deny_cite_only(monkeypatch, str(doc_b.id))
    _inject_providers(monkeypatch, answer="{}")

    outcome = await _ask_inventory(
        transport,
        client=chat_query_client,
        db_session=db_session,
        monkeypatch=monkeypatch,
        user=user,
        organization=organization,
        role=role,
    )

    # B stays listed (readable) for everyone; only its citation is withheld.
    assert "a.pdf" in outcome["answer"]
    assert "b.pdf" in outcome["answer"]
    assert "2 indexed file(s)" in outcome["answer"]
    assert {c["filename"] for c in outcome["citations"]} == expected_cited


async def test_scope_inventory_http_and_websocket_match(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    role = OrganizationRole.member
    user, organization, _ = await _seed_principal(db_session, role=role)
    await _seed_document_with_chunk(
        db_session, organization=organization, uploader=user, filename="a.pdf", text="Alpha text."
    )
    doc_b, _chunk_b = await _seed_document_with_chunk(
        db_session, organization=organization, uploader=user, filename="b.pdf", text="Beta text."
    )
    await db_session.commit()
    _deny_cite_only(monkeypatch, str(doc_b.id))
    _inject_providers(monkeypatch, answer="{}")

    results = {}
    for transport in TRANSPORTS:
        results[transport] = await _ask_inventory(
            transport,
            client=chat_query_client,
            db_session=db_session,
            monkeypatch=monkeypatch,
            user=user,
            organization=organization,
            role=role,
        )

    assert results["http"]["answer"] == results["ws"]["answer"]
    assert {c["filename"] for c in results["http"]["citations"]} == {
        c["filename"] for c in results["ws"]["citations"]
    }
