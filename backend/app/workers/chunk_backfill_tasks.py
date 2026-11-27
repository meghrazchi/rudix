"""Chunk tenant backfill: ``documents.chunks.backfill_tenant`` (R06-09).

Fills ``document_chunks.organization_id``, ``fts_config`` and ``fts_vector`` for rows
written before 0.6.0, from the owning document. It walks the table by primary key in
batches of ``CHUNK_BACKFILL_BATCH_SIZE``; each batch is one short transaction with
``SET LOCAL lock_timeout`` and ``statement_timeout``, so it never holds a long lock. Only
rows whose ``organization_id`` is still NULL are touched, so a rerun or a retry is a no-op
on rows already done (idempotent), and the cursor (the last primary key of the previous
batch) travels in the task kwargs, so a retried or re-enqueued task resumes where it
stopped. After ``max_batches`` batches the task re-enqueues itself with the cursor and
ends, keeping each delivery short.

The task is cross-tenant and uses ``maintenance_session()``; point
``DATABASE_MAINTENANCE_URL`` at the ``BYPASSRLS`` role so documents are visible under
strict RLS. ``scripts/backfill_chunk_tenant.py`` runs the same batches synchronously.
``NOT NULL`` and the RLS policy are a separate operator step
(``deploy/sql/document_chunks_not_null.sql``), never a migration.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_chunk_backfill_rows
from app.db.session import maintenance_session
from app.domains.documents.services.fts_config import fts_config_case_sql
from app.workers.async_runtime import run_async
from app.workers.base_task import RudixTask, TransientTaskError
from app.workers.celery_app import celery_app

TASK_NAME = "documents.chunks.backfill_tenant"
DEFAULT_MAX_BATCHES_PER_TASK = 20

_logger = get_logger("events.maintenance")

SessionScope = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_CONFIG_CASE = fts_config_case_sql("d.language")

# One batch: pick the next ids by primary key, update them from their document, and report
# how many were picked and updated and the last id (the next cursor). ``FOR UPDATE OF c``
# locks only the batch's rows; lock_timeout bounds the wait.
BACKFILL_BATCH_SQL = f"""
WITH batch AS (
    SELECT c.id
    FROM document_chunks AS c
    WHERE c.organization_id IS NULL
      AND (CAST(:cursor AS uuid) IS NULL OR c.id > CAST(:cursor AS uuid))
    ORDER BY c.id
    LIMIT :batch_size
    FOR UPDATE OF c
),
updated AS (
    UPDATE document_chunks AS c
    SET organization_id = d.organization_id,
        fts_config = cfg.name,
        fts_vector = to_tsvector(CAST(cfg.name AS regconfig), COALESCE(c.text, ''))
    FROM batch AS b
    JOIN documents AS d ON TRUE
    CROSS JOIN LATERAL (SELECT {_CONFIG_CASE} AS name) AS cfg
    WHERE c.id = b.id
      AND c.document_id = d.id
      AND c.organization_id IS NULL
    RETURNING c.id
)
SELECT
    (SELECT count(*) FROM batch) AS scanned,
    (SELECT count(*) FROM updated) AS updated,
    (SELECT b.id FROM batch AS b ORDER BY b.id DESC LIMIT 1) AS last_id
"""

REMAINING_SQL = "SELECT count(*) FROM document_chunks WHERE organization_id IS NULL"


@dataclass(frozen=True)
class BackfillBatch:
    scanned: int
    updated: int
    last_id: UUID | None

    @property
    def done(self) -> bool:
        return self.last_id is None


@dataclass
class BackfillProgress:
    cursor: UUID | None
    batches: int = 0
    updated: int = 0
    finished: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "cursor": str(self.cursor) if self.cursor else None,
            "batches": self.batches,
            "updated": self.updated,
            "finished": self.finished,
        }


def default_session_scope() -> AbstractAsyncContextManager[AsyncSession]:
    return maintenance_session()


async def _set_local_timeouts(session: AsyncSession) -> None:
    # SET LOCAL cannot take bind parameters; the values are validated integers.
    lock_ms = int(settings.chunk_backfill_lock_timeout_ms)
    statement_ms = int(settings.chunk_backfill_statement_timeout_ms)
    await session.execute(text(f"SET LOCAL lock_timeout = '{lock_ms}ms'"))
    await session.execute(text(f"SET LOCAL statement_timeout = '{statement_ms}ms'"))


async def run_backfill_batch(
    *,
    cursor: UUID | None,
    batch_size: int | None = None,
    session_scope: SessionScope = default_session_scope,
) -> BackfillBatch:
    """Run one batch in its own transaction and return what it did."""
    size = int(batch_size or settings.chunk_backfill_batch_size)
    async with session_scope() as session:
        async with session.begin():
            await _set_local_timeouts(session)
            row = (
                await session.execute(
                    text(BACKFILL_BATCH_SQL),
                    {"cursor": str(cursor) if cursor else None, "batch_size": size},
                )
            ).one()
    last_id = row.last_id
    batch = BackfillBatch(
        scanned=int(row.scanned or 0),
        updated=int(row.updated or 0),
        last_id=UUID(str(last_id)) if last_id is not None else None,
    )
    record_chunk_backfill_rows(batch.updated)
    return batch


async def count_remaining(session_scope: SessionScope = default_session_scope) -> int:
    """Chunks whose organization_id is still NULL (dry runs and progress output)."""
    async with session_scope() as session:
        value = (await session.execute(text(REMAINING_SQL))).scalar_one()
        await session.rollback()
    return int(value or 0)


async def backfill(
    *,
    cursor: UUID | None = None,
    max_batches: int | None = None,
    batch_size: int | None = None,
    session_scope: SessionScope = default_session_scope,
    on_batch: Callable[[BackfillBatch, BackfillProgress], None] | None = None,
) -> BackfillProgress:
    """Run batches from ``cursor`` until the table is done or ``max_batches`` ran."""
    progress = BackfillProgress(cursor=cursor)
    while max_batches is None or progress.batches < max_batches:
        batch = await run_backfill_batch(
            cursor=progress.cursor, batch_size=batch_size, session_scope=session_scope
        )
        if batch.done:
            progress.finished = True
            break
        progress.batches += 1
        progress.updated += batch.updated
        progress.cursor = batch.last_id
        if on_batch is not None:
            on_batch(batch, progress)
    return progress


def _parse_cursor(value: str | None) -> UUID | None:
    if not value:
        return None
    return UUID(str(value))


@celery_app.task(name=TASK_NAME, bind=True, base=RudixTask, ignore_result=True)
def backfill_chunk_tenant(
    self: RudixTask,
    cursor: str | None = None,
    max_batches: int = DEFAULT_MAX_BATCHES_PER_TASK,
    total_updated: int = 0,
) -> dict[str, Any]:
    """Backfill up to ``max_batches`` batches, then re-enqueue from the new cursor."""
    try:
        progress = run_async(backfill(cursor=_parse_cursor(cursor), max_batches=max_batches))
    except DBAPIError as exc:
        # lock_timeout or statement_timeout: retry the same cursor later (resumable).
        _logger.warning(
            "documents.chunks.backfill_tenant.batch_failed",
            cursor=cursor,
            error_type=type(exc.orig).__name__ if exc.orig is not None else type(exc).__name__,
        )
        raise TransientTaskError("chunk backfill batch failed") from exc
    total = int(total_updated) + progress.updated
    result = {**progress.as_dict(), "total_updated": total}
    _logger.info(
        "documents.chunks.backfill_tenant.progress",
        batches=progress.batches,
        updated=progress.updated,
        total_updated=total,
        finished=progress.finished,
    )
    if not progress.finished:
        backfill_chunk_tenant.apply_async(
            kwargs={
                "cursor": str(progress.cursor) if progress.cursor else None,
                "max_batches": max_batches,
                "total_updated": total,
            }
        )
    return result
