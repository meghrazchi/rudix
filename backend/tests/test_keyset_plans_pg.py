"""R04-04: keyset page queries are index range scans on PostgreSQL, not OFFSET skips.

The test database is nearly empty, so plans are checked with ``enable_seqscan = off``: that
proves the index is usable for the cursor predicate, not that the planner picks it by cost
on production volume (that is the manual load-test step in the plan). When the A1 index a
query needs is not migrated yet the test is skipped with the missing index named.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.domains.chat.repositories.chat import _message_sort_columns, message_sort_key
from app.models.chat import ChatMessage
from app.models.document import Document
from app.shared.pagination import apply_keyset
from tests.list_endpoint_seed import seed_chat_session, seed_document, seed_tenant, seed_turns
from tests.pg_plans import compact_indexes, seed_document_statistics

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]


def _nodes(plan: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


async def _explain(session: AsyncSession, statement: Select[Any]) -> list[dict[str, Any]]:
    connection = await session.connection()
    compiled = statement.compile(dialect=connection.dialect)
    params = compiled.construct_params()
    positional = tuple(params[name] for name in (compiled.positiontup or []))
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    result = await connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {compiled}", positional)
    raw = result.scalar_one()
    document = json.loads(raw) if isinstance(raw, str) else raw
    return list(_nodes(document[0]["Plan"]))


async def _index_on(session: AsyncSession, table: str, fragment: str) -> str | None:
    result = await session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :table"),
        {"table": table},
    )
    for name, definition in result.all():
        if fragment in definition:
            return str(name)
    return None


def _assert_index_scan(nodes: list[dict[str, Any]], table: str, index: str) -> None:
    on_table = [node for node in nodes if node.get("Relation Name") == table]
    assert on_table, f"plan does not read {table}"
    assert all(node["Node Type"] != "Seq Scan" for node in on_table), nodes
    assert any(node.get("Index Name") == index for node in on_table), nodes
    limits = [node for node in nodes if node["Node Type"] == "Limit"]
    assert limits, "keyset page query must be LIMITed"


async def test_documents_cursor_page_uses_index(pg_session: AsyncSession) -> None:
    index = await _index_on(pg_session, "documents", "(organization_id, created_at DESC, id DESC)")
    # R04-02 (A1) ships this index in Alembic 20261127_0002; a missing index is a failure.
    assert index is not None, "documents(organization_id, created_at DESC, id DESC) is missing"
    tenant = await seed_tenant(pg_session)
    documents = [(await seed_document(pg_session, tenant, chunks=0))[0] for _ in range(5)]
    await pg_session.flush()
    # 0.9.0 (S1): real statistics so the planner's index choice is deterministic.
    await seed_document_statistics(
        pg_session, organization_id=tenant.org_id, user_id=tenant.user.id
    )
    await compact_indexes(pg_session, "documents")
    last = documents[2]
    statement = apply_keyset(
        Document.__table__.select()  # type: ignore[attr-defined]
        .where(Document.organization_id == tenant.org_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(21),
        [Document.created_at, Document.id],
        True,
        [last.created_at, last.id],
    )
    _assert_index_scan(await _explain(pg_session, statement), "documents", index)


async def test_messages_cursor_page_uses_index(pg_session: AsyncSession) -> None:
    index = await _index_on(pg_session, "chat_messages", "(chat_session_id, created_at")
    if index is None:
        pytest.skip("no chat_messages(chat_session_id, created_at...) index is present")
    tenant = await seed_tenant(pg_session)
    document, chunks = await seed_document(pg_session, tenant)
    chat_session = await seed_chat_session(pg_session, tenant)
    await seed_turns(pg_session, chat_session, turns=3, document=document, chunk=chunks[0])
    await pg_session.flush()
    await compact_indexes(pg_session, "chat_messages")
    first = (
        (
            await pg_session.execute(
                ChatMessage.__table__.select()  # type: ignore[attr-defined]
                .where(ChatMessage.chat_session_id == chat_session.id)
                .limit(1)
            )
        )
        .mappings()
        .one()
    )
    message = await pg_session.get(ChatMessage, first["id"])
    assert message is not None
    columns = _message_sort_columns()
    statement = apply_keyset(
        ChatMessage.__table__.select()  # type: ignore[attr-defined]
        .where(ChatMessage.chat_session_id == chat_session.id)
        .order_by(*(column.asc() for column in columns))
        .limit(201),
        columns,
        False,
        message_sort_key(message),
    )
    _assert_index_scan(await _explain(pg_session, statement), "chat_messages", index)
