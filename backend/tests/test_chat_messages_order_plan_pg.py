"""R05-11: the newest-first messages page reads the existing messages index backwards.

Same method as ``test_keyset_plans_pg.py``: ``enable_seqscan = off`` on a nearly empty,
re-indexed table proves the index is usable for the descending keyset predicate; it does not
claim the planner picks it by cost on production volume.
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
from app.shared.pagination import apply_keyset
from tests.list_endpoint_seed import seed_chat_session, seed_document, seed_tenant, seed_turns
from tests.pg_plans import compact_indexes

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]

INDEX = "idx_chat_messages_session"


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


def _desc_statement(chat_session_id: Any, keyset: list[Any] | None) -> Select[Any]:
    columns = _message_sort_columns()
    statement = (
        ChatMessage.__table__.select()  # type: ignore[attr-defined]
        .where(ChatMessage.chat_session_id == chat_session_id)
        .order_by(*(column.desc() for column in columns))
        .limit(201)
    )
    if keyset is None:
        return statement
    return apply_keyset(statement, columns, True, keyset)


def _assert_backward_index_scan(nodes: list[dict[str, Any]]) -> None:
    on_table = [node for node in nodes if node.get("Relation Name") == "chat_messages"]
    assert on_table, "plan does not read chat_messages"
    assert all(node["Node Type"] != "Seq Scan" for node in on_table), nodes
    scans = [node for node in on_table if node.get("Index Name") == INDEX]
    assert scans, nodes
    assert all(node.get("Scan Direction") == "Backward" for node in scans), scans
    assert any(node["Node Type"] == "Limit" for node in nodes), "page query must be LIMITed"


async def test_desc_messages_page_scans_index_backward(pg_session: AsyncSession) -> None:
    result = await pg_session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": INDEX}
    )
    definition = result.scalar_one_or_none()
    assert definition is not None and "(chat_session_id, created_at)" in definition, definition

    tenant = await seed_tenant(pg_session)
    document, chunks = await seed_document(pg_session, tenant)
    chat_session = await seed_chat_session(pg_session, tenant)
    await seed_turns(pg_session, chat_session, turns=3, document=document, chunk=chunks[0])
    await pg_session.flush()
    await compact_indexes(pg_session, "chat_messages")

    # First page (no cursor) and a later page (descending keyset predicate).
    _assert_backward_index_scan(await _explain(pg_session, _desc_statement(chat_session.id, None)))
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
    keyset = message_sort_key(message)
    _assert_backward_index_scan(
        await _explain(pg_session, _desc_statement(chat_session.id, keyset))
    )
