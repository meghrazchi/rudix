"""Streamed admin exports (R04-04).

The usage and audit exports used to load every row into memory and build the whole body
before sending it. They now read rows in batches from a dedicated session that lives as long
as the response body, and write the same bytes the old code produced:

* CSV: the existing serializer runs per batch and the header is kept only once.
* JSON: the old body was ``json.dumps(payload, sort_keys=True)``. Every top-level key that
  sorts before ``items`` is written first, then the items one by one, then the keys that sort
  after it (``max_rows``, ``organization_id``, ``range``, ``returned``), so ``returned`` can
  be written once the row count is known.

The organisation is resolved from the authenticated principal before streaming starts and
the statements always filter by it; the export session is also bound to that tenant.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from time import perf_counter
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.sql import Select

from app.core.logging import get_logger
from app.db.session import get_db_session
from app.db.tenant_context import bind_session_tenant

ExportSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

EXPORT_BATCH_SIZE = 500
_ITEMS_KEY = "items"
_CSV_LINE_END = "\r\n"

_logger = get_logger("events.admin.export")


def session_factory_for(bind: AsyncEngine | AsyncConnection | None) -> ExportSessionFactory:
    """A factory of fresh sessions on ``bind`` with the ``SessionLocal`` options."""

    def _factory() -> AbstractAsyncContextManager[AsyncSession]:
        return AsyncSession(bind=bind, autoflush=False, expire_on_commit=False)

    return _factory


async def get_export_session_factory(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExportSessionFactory:
    """FastAPI dependency: open the export's own session on the request session's bind.

    The request session can be closed once the handler returns, before the body is sent, so
    the body reads through a separate session. It reuses the request session's bind (the
    application engine in production) rather than building a new engine.
    """
    return session_factory_for(db_session.bind)


async def stream_scalar_batches(
    session_factory: ExportSessionFactory,
    *,
    organization_id: UUID,
    statement: Select[Any],
    batch_size: int | None = None,
) -> AsyncIterator[list[Any]]:
    """Yield ORM rows of ``statement`` in batches from a session opened for the stream."""
    size = batch_size or EXPORT_BATCH_SIZE
    async with session_factory() as session:
        bind_session_tenant(session, organization_id)
        result = await session.stream(
            statement.execution_options(stream_results=True, yield_per=size)
        )
        async for partition in result.scalars().partitions(size):
            yield list(partition)


def _strip_csv_header(text: str) -> str:
    _, separator, rest = text.partition(_CSV_LINE_END)
    return rest if separator else ""


async def stream_csv[RowT](
    batches: AsyncIterator[list[RowT]],
    serialize: Callable[[list[RowT]], str],
) -> AsyncIterator[str]:
    """``serialize(all_rows)`` written batch by batch; the header line is emitted once."""
    header_sent = False
    async for batch in batches:
        text = serialize(batch)
        if header_sent:
            text = _strip_csv_header(text)
        header_sent = True
        if text:
            yield text
    if not header_sent:
        yield serialize([])


def _check_key_order(head: Mapping[str, Any], tail: Mapping[str, Any]) -> None:
    if any(key >= _ITEMS_KEY for key in head) or any(key <= _ITEMS_KEY for key in tail):
        raise ValueError("head keys must sort before 'items' and tail keys after it")


async def stream_json(
    *,
    head: Mapping[str, Any],
    batches: AsyncIterator[Sequence[Mapping[str, Any]]],
    tail: Callable[[int], Mapping[str, Any]],
) -> AsyncIterator[str]:
    """Write ``json.dumps({**head, "items": [...], **tail(count)}, sort_keys=True)`` lazily."""
    _check_key_order(head, tail(0))
    opening = json.dumps(dict(head), sort_keys=True)[:-1]
    separator = ", " if head else ""
    yield f'{opening}{separator}"{_ITEMS_KEY}": ['
    count = 0
    async for batch in batches:
        if not batch:
            continue
        encoded = ", ".join(json.dumps(dict(item), sort_keys=True) for item in batch)
        yield encoded if count == 0 else f", {encoded}"
        count += len(batch)
    closing = json.dumps(dict(tail(count)), sort_keys=True)
    yield f"], {closing[1:]}" if closing != "{}" else "]}"


async def map_batches[InT, OutT](
    batches: AsyncIterator[list[InT]],
    transform: Callable[[InT], OutT],
) -> AsyncIterator[list[OutT]]:
    async for batch in batches:
        yield [transform(row) for row in batch]


async def logged_stream(
    chunks: AsyncIterator[str],
    *,
    export: str,
    export_format: str,
    organization_id: UUID,
    user_id: str | None,
) -> AsyncIterator[str]:
    """Pass ``chunks`` through and log size and latency (no row content) when done."""
    started = perf_counter()
    total_bytes = 0
    status = "failed"
    try:
        async for chunk in chunks:
            total_bytes += len(chunk)
            yield chunk
        status = "completed"
    finally:
        _logger.info(
            "admin.export.streamed",
            export=export,
            export_format=export_format,
            organization_id=str(organization_id),
            user_id=user_id,
            status=status,
            bytes=total_bytes,
            latency_ms=round((perf_counter() - started) * 1000, 2),
        )
