"""R04-04: keyset cursors walk exactly the rows the offset walk returns.

Rows are inserted in one transaction, so on PostgreSQL they share ``created_at`` (and on
SQLite they share the second); the tie-breaking keys are what keeps the walks equal.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.notifications.repositories.notifications import NotificationRepository
from app.models.enums import NotificationEventType, NotificationSeverity
from app.models.usage import AuditLog
from app.models.webhook import Webhook, WebhookDelivery
from app.shared.pagination import decode_cursor, encode_cursor
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
ROWS = 8


@pytest.fixture(autouse=True)
def _app_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_app_auth(monkeypatch)


def _join(url: str, **params: Any) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items() if value is not None)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}" if query else url


async def _get(client: AsyncClient, tenant: Tenant, url: str) -> dict[str, Any]:
    response = await client.get(url, headers=tenant.headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _offset_walk(
    client: AsyncClient, tenant: Tenant, url: str, key: Callable[[dict], str], items: str
) -> list[str]:
    seen: list[str] = []
    offset = 0
    while True:
        body = await _get(client, tenant, _join(url, limit=PAGE, offset=offset))
        page = [key(item) for item in body[items]]
        seen.extend(page)
        if len(page) < PAGE:
            return seen
        offset += PAGE


async def _cursor_walk(
    client: AsyncClient, tenant: Tenant, url: str, key: Callable[[dict], str], items: str
) -> list[str]:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(ROWS + 2):
        body = await _get(client, tenant, _join(url, limit=PAGE, cursor=cursor))
        seen.extend(key(item) for item in body[items])
        cursor = body["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("cursor walk did not terminate")


async def _assert_walks_equal(
    client: AsyncClient,
    tenant: Tenant,
    url: str,
    key: Callable[[dict], str],
    *,
    items: str = "items",
    expected: int = ROWS,
) -> list[str]:
    offset_ids = await _offset_walk(client, tenant, url, key, items)
    cursor_ids = await _cursor_walk(client, tenant, url, key, items)
    assert len(offset_ids) == expected
    assert len(set(offset_ids)) == expected
    assert cursor_ids == offset_ids
    return cursor_ids


async def _seed_notifications(db_session: AsyncSession, tenant: Tenant, count: int) -> None:
    repository = NotificationRepository()
    for index in range(count):
        await repository.create_notification(
            db_session,
            organization_id=tenant.org_id,
            user_id=tenant.user.id,
            event_type=NotificationEventType.upload_indexed,
            severity=NotificationSeverity.info,
            title=f"Notification {index}",
        )


def _seed_audit_logs(db_session: AsyncSession, tenant: Tenant, count: int) -> None:
    db_session.add_all(
        AuditLog(
            organization_id=tenant.org_id,
            user_id=tenant.user.id,
            action="document.viewed",
            resource_type="document",
            resource_id=uuid4(),
            metadata_json={"index": index},
        )
        for index in range(count)
    )


async def _seed_webhook(db_session: AsyncSession, tenant: Tenant, deliveries: int) -> Webhook:
    webhook = Webhook(
        organization_id=tenant.org_id,
        name=f"Hook {uuid4().hex[:6]}",
        url="https://hooks.example.test/rudix",
        secret_prefix="whsec_test",
        secret_hash="0" * 64,
        event_types=["document.indexed"],
        status="active",
        retry_policy={},
        created_by_id=tenant.user.id,
    )
    db_session.add(webhook)
    await db_session.flush()
    db_session.add_all(
        WebhookDelivery(
            webhook_id=webhook.id,
            organization_id=tenant.org_id,
            event_type="document.indexed",
            payload={"index": index},
            status="delivered",
            attempt_count=1,
        )
        for index in range(deliveries)
    )
    await db_session.flush()
    return webhook


async def test_chat_sessions_cursor_walk(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    for index in range(ROWS):
        await seed_chat_session(db_session, tenant, title=f"Session {index}")
    await db_session.commit()
    async with api_client(monkeypatch, db_session) as client:
        await _assert_walks_equal(
            client, tenant, "/api/v1/chat/sessions", lambda item: item["session_id"]
        )


async def test_chat_messages_cursor_walk(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    document, chunks = await seed_document(db_session, tenant)
    chat_session = await seed_chat_session(db_session, tenant)
    await seed_turns(db_session, chat_session, turns=4, document=document, chunk=chunks[0])
    await db_session.commit()
    url = f"/api/v1/chat/sessions/{chat_session.id}/messages"
    async with api_client(monkeypatch, db_session) as client:
        ids = await _assert_walks_equal(client, tenant, url, lambda item: item["message_id"])
        body = await _get(client, tenant, _join(url, limit=ROWS))
        # Within a shared timestamp the user turn still precedes the answer.
        roles = [item["role"] for item in body["items"]]
        assert [item["message_id"] for item in body["items"]] == ids
        assert roles.count("user") == roles.count("assistant") == 4


@pytest.mark.parametrize("sort_order", ["desc", "asc"])
async def test_documents_cursor_walk(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, sort_order: str
) -> None:
    tenant = await seed_tenant(db_session)
    for _ in range(ROWS):
        await seed_document(db_session, tenant, chunks=0)
    await db_session.commit()
    url = f"/api/v1/documents?sort_by=created_at&sort_order={sort_order}"
    async with api_client(monkeypatch, db_session) as client:
        await _assert_walks_equal(client, tenant, url, lambda item: item["document_id"])


async def test_notifications_cursor_walk(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    await _seed_notifications(db_session, tenant, ROWS)
    await db_session.commit()
    async with api_client(monkeypatch, db_session) as client:
        await _assert_walks_equal(
            client, tenant, "/api/v1/notifications", lambda item: item["notification_id"]
        )
        body = await _get(client, tenant, "/api/v1/notifications?limit=2&include_total=false")
        assert body["total"] is None
        assert body["unread_count"] == ROWS


async def test_audit_logs_cursor_walk(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    _seed_audit_logs(db_session, tenant, ROWS)
    await db_session.commit()
    async with api_client(monkeypatch, db_session) as client:
        await _assert_walks_equal(
            client,
            tenant,
            "/api/v1/admin/audit-logs?action=document.viewed",
            lambda item: item["audit_log_id"],
        )


async def test_webhook_deliveries_cursor_walk_and_limit(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    webhook = await _seed_webhook(db_session, tenant, ROWS)
    await db_session.commit()
    url = f"/api/v1/admin/webhooks/{webhook.id}/deliveries"
    async with api_client(monkeypatch, db_session) as client:
        cursor_ids: list[str] = []
        cursor: str | None = None
        while True:
            body = await _get(client, tenant, _join(url, limit=PAGE, cursor=cursor))
            assert body["total"] == len(body["items"])
            cursor_ids.extend(item["id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
        everything = await _get(client, tenant, url)
        assert [item["id"] for item in everything["items"]] == cursor_ids
        assert everything["next_cursor"] is None
        assert len(cursor_ids) == ROWS

        two = await _get(client, tenant, _join(url, limit=2))
        assert len(two["items"]) == 2 and two["next_cursor"]
        too_many = await client.get(_join(url, limit=201), headers=tenant.headers)
        assert too_many.status_code == 422


async def test_include_total_defaults(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    for _ in range(4):
        await seed_document(db_session, tenant, chunks=0)
    await db_session.commit()
    async with api_client(monkeypatch, db_session) as client:
        first = await _get(client, tenant, "/api/v1/documents?limit=2")
        assert first["total"] == 4
        cursor = first["next_cursor"]
        assert cursor
        second = await _get(client, tenant, _join("/api/v1/documents?limit=2", cursor=cursor))
        assert second["total"] is None
        counted = await _get(
            client, tenant, _join("/api/v1/documents?limit=2&include_total=true", cursor=cursor)
        )
        assert counted["total"] == 4
        assert counted["items"] == second["items"]
        uncounted = await _get(client, tenant, "/api/v1/documents?limit=2&include_total=false")
        assert uncounted["total"] is None
        last = await _get(client, tenant, "/api/v1/documents?limit=4")
        assert last["next_cursor"] is None


def _tampered(cursor: str) -> list[str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))

    def encode(value: Any) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return [
        "not-a-cursor!",
        cursor[:-2],
        encode({**payload, "v": 2}),
        encode({**payload, "s": "notifications.created_at.desc"}),
        encode({**payload, "k": [["x", 1], ["u", "nope"]]}),
        encode({**payload, "k": []}),
        encode(["not", "an", "object"]),
        "A" * 2000,
    ]


async def test_tampered_cursor_is_rejected(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    for _ in range(3):
        await seed_document(db_session, tenant, chunks=0)
    await db_session.commit()
    async with api_client(monkeypatch, db_session) as client:
        cursor = (await _get(client, tenant, "/api/v1/documents?limit=1"))["next_cursor"]
        for bad in _tampered(cursor):
            response = await client.get(
                _join("/api/v1/documents?limit=1", cursor=bad), headers=tenant.headers
            )
            assert response.status_code in {400, 422}, bad
            if response.status_code == 400:
                assert response.json()["detail"] == "Invalid pagination cursor"

        # A desc cursor cannot be replayed against the asc order.
        response = await client.get(
            _join("/api/v1/documents?limit=1&sort_order=asc", cursor=cursor),
            headers=tenant.headers,
        )
        assert response.status_code == 400

        response = await client.get(
            _join("/api/v1/documents?limit=1&offset=2", cursor=cursor), headers=tenant.headers
        )
        assert response.status_code == 400
        assert "offset" in response.json()["detail"]

        response = await client.get(
            _join("/api/v1/documents?limit=1&sort_by=filename", cursor=cursor),
            headers=tenant.headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Cursor pagination requires sort_by=created_at"

        # Other sort orders keep working without cursors and do not offer one.
        body = await _get(client, tenant, "/api/v1/documents?limit=1&sort_by=filename")
        assert body["next_cursor"] is None


async def test_cursor_from_other_org_returns_only_own_rows(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    org_a = await seed_tenant(db_session)
    org_b = await seed_tenant(db_session)
    for _ in range(4):
        await seed_document(db_session, org_a, chunks=0)
    own_b = [(await seed_document(db_session, org_b, chunks=0))[0] for _ in range(2)]
    await seed_chat_session(db_session, org_a)
    await seed_chat_session(db_session, org_a)
    await db_session.commit()
    async with api_client(monkeypatch, db_session) as client:
        cursor_a = (await _get(client, org_a, "/api/v1/documents?limit=1"))["next_cursor"]
        # A cursor far in the "future" would cover every row: still only org B's rows.
        values = decode_cursor(cursor_a, "documents.created_at.desc")
        forged = encode_cursor(
            "documents.created_at.desc",
            [values[0].replace(year=values[0].year + 1), values[1]],
        )
        for cursor in (cursor_a, forged):
            body = await _get(client, org_b, _join("/api/v1/documents?limit=50", cursor=cursor))
            ids = {item["document_id"] for item in body["items"]}
            assert ids <= {str(document.id) for document in own_b}
        body = await _get(client, org_b, _join("/api/v1/documents?limit=50", cursor=forged))
        assert {item["document_id"] for item in body["items"]} == {str(d.id) for d in own_b}

        sessions_a = await _get(client, org_a, "/api/v1/chat/sessions?limit=1")
        body = await _get(
            client,
            org_b,
            _join("/api/v1/chat/sessions?limit=50", cursor=sessions_a["next_cursor"]),
        )
        assert body["items"] == []
