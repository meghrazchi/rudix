"""R05-11: ``GET /chat/sessions/{id}/messages?order=desc`` pages newest first.

Rows are inserted in one transaction, so on PostgreSQL they share ``created_at`` (and on
SQLite they share the second); the role rank and id keep both walks total and stable.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.token_codec import create_app_access_token
from app.domains.chat.repositories.chat import (
    MESSAGE_SORT_NAME,
    MESSAGE_SORT_NAME_DESC,
    ChatRepository,
)
from app.models.enums import OrganizationRole
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.shared.pagination import decode_cursor
from tests.list_endpoint_seed import (
    Tenant,
    api_client,
    configure_app_auth,
    seed_chat_session,
    seed_document,
    seed_tenant,
    seed_turns,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]

PAGE = 3
TURNS = 5


@pytest.fixture(autouse=True)
def _app_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_app_auth(monkeypatch)


def _url(session_id: object, **params: Any) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items() if value is not None)
    base = f"/api/v1/chat/sessions/{session_id}/messages"
    return f"{base}?{query}" if query else base


async def _walk(client: AsyncClient, tenant: Tenant, session_id: object, order: str) -> list[str]:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(TURNS * 2 + 2):
        response = await client.get(
            _url(session_id, limit=PAGE, order=order, cursor=cursor), headers=tenant.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        seen.extend(item["message_id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("cursor walk did not terminate")


async def _seeded_session(db_session: AsyncSession) -> tuple[Tenant, Any]:
    tenant = await seed_tenant(db_session)
    document, chunks = await seed_document(db_session, tenant)
    chat_session = await seed_chat_session(db_session, tenant)
    await seed_turns(db_session, chat_session, turns=TURNS, document=document, chunk=chunks[0])
    await db_session.commit()
    return tenant, chat_session


async def test_desc_walk_is_reversed_asc_walk(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant, chat_session = await _seeded_session(db_session)
    async with api_client(monkeypatch, db_session) as client:
        asc_ids = await _walk(client, tenant, chat_session.id, "asc")
        desc_ids = await _walk(client, tenant, chat_session.id, "desc")
        default_ids = await _walk(client, tenant, chat_session.id, "asc")
        response = await client.get(_url(chat_session.id, limit=PAGE), headers=tenant.headers)
        first_default = [item["message_id"] for item in response.json()["items"]]

    assert len(asc_ids) == TURNS * 2
    assert len(set(asc_ids)) == TURNS * 2
    assert desc_ids == list(reversed(asc_ids))
    # Omitting ``order`` keeps today's ascending behaviour.
    assert default_ids == asc_ids
    assert first_default == asc_ids[:PAGE]


async def test_desc_page_items_are_newest_first_with_desc_cursor(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant, chat_session = await _seeded_session(db_session)
    async with api_client(monkeypatch, db_session) as client:
        response = await client.get(
            _url(chat_session.id, limit=2, order="desc"), headers=tenant.headers
        )
    assert response.status_code == 200
    body = response.json()
    # Within a timestamp the answer ranks after its question, so it comes first backwards.
    assert body["items"][0]["role"] == "assistant"
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    assert decode_cursor(body["next_cursor"], MESSAGE_SORT_NAME_DESC)


async def test_cursor_from_one_order_is_rejected_by_the_other(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant, chat_session = await _seeded_session(db_session)
    async with api_client(monkeypatch, db_session) as client:
        asc = (
            await client.get(_url(chat_session.id, limit=2, order="asc"), headers=tenant.headers)
        ).json()
        desc = (
            await client.get(_url(chat_session.id, limit=2, order="desc"), headers=tenant.headers)
        ).json()
        assert decode_cursor(asc["next_cursor"], MESSAGE_SORT_NAME)
        crossed = [
            _url(chat_session.id, limit=2, order="desc", cursor=asc["next_cursor"]),
            _url(chat_session.id, limit=2, order="asc", cursor=desc["next_cursor"]),
            _url(chat_session.id, limit=2, cursor=desc["next_cursor"]),
        ]
        for url in crossed:
            response = await client.get(url, headers=tenant.headers)
            assert response.status_code == 400, url
            assert response.json()["detail"] == "Invalid pagination cursor"

        response = await client.get(_url(chat_session.id, order="sideways"), headers=tenant.headers)
        assert response.status_code == 422


async def test_other_users_session_is_not_found_in_both_orders(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant, chat_session = await _seeded_session(db_session)
    suffix = uuid4().hex[:10]
    intruder = User(
        organization_id=tenant.org_id,
        external_auth_id=f"c2-intruder-{suffix}",
        email=f"c2-intruder-{suffix}@example.com",
        display_name="Other member",
    )
    db_session.add(intruder)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=tenant.org_id,
            user_id=intruder.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db_session.commit()
    token = create_app_access_token(
        subject=intruder.external_auth_id,
        organization_id=str(tenant.org_id),
        expires_in_seconds=600,
    )
    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": str(tenant.org_id)}
    other_org = await seed_tenant(db_session)
    async with api_client(monkeypatch, db_session) as client:
        for order in ("asc", "desc"):
            response = await client.get(_url(chat_session.id, order=order), headers=headers)
            assert response.status_code == 404
            assert response.json()["detail"] == "Chat session not found"
            response = await client.get(
                _url(chat_session.id, order=order), headers=other_org.headers
            )
            assert response.status_code == 404


async def test_repository_desc_offset_and_keyset(db_session: AsyncSession) -> None:
    tenant, chat_session = await _seeded_session(db_session)
    repository = ChatRepository()
    ascending = await repository.list_chat_messages(db_session, chat_session_id=chat_session.id)
    descending = await repository.list_chat_messages(
        db_session, chat_session_id=chat_session.id, descending=True
    )
    assert [m.id for m in descending] == [m.id for m in reversed(ascending)]
    shifted = await repository.list_chat_messages(
        db_session, chat_session_id=chat_session.id, descending=True, offset=2, limit=2
    )
    assert [m.id for m in shifted] == [m.id for m in descending[2:4]]
    assert tenant.org_id is not None
