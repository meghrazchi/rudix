"""Transactional outbox for request-path task dispatch (R06-01 part 2, plan contract 4.2.5).

``await enqueue(session, *, organization_id, task_name, kwargs, queue, dedupe_key)`` adds an
``outbox_messages`` row in the caller's transaction, so the dispatch commits or rolls back
with the document change that needs it. A ``dedupe_key`` that already exists is a no-op.

``await publish_after_commit(session)`` runs after the caller's commit: it publishes every
row this session enqueued (in a worker thread, so broker I/O never blocks the event loop)
and marks it ``published``. A failed publication leaves the row ``pending`` with a backoff;
the ``outbox.relay`` beat task publishes it later. Consumers are idempotent (a duplicate
``documents.process`` finds the claim held), so publishing twice is harmless.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.metrics_workers import record_outbox_message
from app.models.outbox import OutboxMessage

PENDING, PUBLISHED, FAILED = "pending", "published", "failed"
_SESSION_KEY = "outbox_pending"
logger = get_logger("events.outbox")


@dataclass
class PendingDispatch:
    message_id: UUID
    organization_id: UUID
    task_name: str
    kwargs: dict[str, Any]
    queue: str | None
    # The task object to publish with (request paths pass the one they were given, so
    # tests can substitute a fake); None resolves ``task_name`` on the Celery app.
    task: Any = None


@dataclass
class PublishOutcome:
    message_id: UUID
    task_name: str
    result: Any = None
    error: Exception | None = None

    @property
    def published(self) -> bool:
        return self.error is None


def backoff_seconds(attempts: int) -> int:
    """2, 4, 8, ... seconds, capped at five minutes."""
    return int(min(300, 2 ** max(attempts, 1)))


def resolve_task(task_name: str) -> Any:
    from app.workers.celery_app import celery_app

    return celery_app.tasks[task_name]


async def enqueue(
    session: AsyncSession,
    *,
    organization_id: UUID,
    task_name: str,
    kwargs: dict[str, Any],
    queue: str | None = None,
    dedupe_key: str | None = None,
    task: Any = None,
) -> UUID | None:
    """Add a pending row in the caller's transaction; None when the dedupe key exists."""
    message_id = uuid4()
    values = {
        "id": message_id,
        "organization_id": organization_id,
        "task_name": task_name,
        "queue": queue,
        "kwargs": kwargs,
        "dedupe_key": dedupe_key,
        "status": PENDING,
        "attempts": 0,
    }
    dialect = session.get_bind().dialect.name
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
    stmt = insert_fn(OutboxMessage).values(**values)
    if dedupe_key is not None:
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"])
    inserted = (await session.execute(stmt.returning(OutboxMessage.id))).scalar_one_or_none()
    if inserted is None:
        record_outbox_message(task_name, "duplicate")
        return None
    session.info.setdefault(_SESSION_KEY, []).append(
        PendingDispatch(message_id, organization_id, task_name, dict(kwargs), queue, task)
    )
    return message_id


def _publish(dispatch: PendingDispatch) -> Any:
    task = dispatch.task if dispatch.task is not None else resolve_task(dispatch.task_name)
    return task.delay(**dispatch.kwargs)


async def publish_after_commit(session: AsyncSession) -> list[PublishOutcome]:
    """Publish the rows this session enqueued, then record the outcome and commit.

    Call it right after the commit that wrote the rows, before any other write on the
    session: it commits its own status updates.
    """
    pending: list[PendingDispatch] = session.info.pop(_SESSION_KEY, [])
    outcomes: list[PublishOutcome] = []
    for dispatch in pending:
        try:
            result = await asyncio.to_thread(_publish, dispatch)
        except Exception as exc:
            outcomes.append(PublishOutcome(dispatch.message_id, dispatch.task_name, error=exc))
            continue
        outcomes.append(PublishOutcome(dispatch.message_id, dispatch.task_name, result=result))
    if not outcomes:
        return outcomes
    now = datetime.now(UTC)
    for outcome in outcomes:
        await session.execute(_outcome_update(outcome, now))
        record_outbox_message(outcome.task_name, "published" if outcome.published else "deferred")
        if not outcome.published:
            logger.warning(
                "outbox.publish_deferred",
                task_name=outcome.task_name,
                message_id=str(outcome.message_id),
                error_type=type(outcome.error).__name__,
            )
    await session.commit()
    return outcomes


def _outcome_update(outcome: PublishOutcome, now: datetime) -> Any:
    row = OutboxMessage
    values: dict[str, Any] = {"attempts": row.attempts + 1, "updated_at": now}
    if outcome.published:
        values.update(status=PUBLISHED, published_at=now, last_error=None)
    else:
        values.update(
            last_error=type(outcome.error).__name__[:128],
            available_at=now + timedelta(seconds=backoff_seconds(1)),
        )
    return (
        update(row)
        .where(row.id == outcome.message_id, row.status == PENDING)
        .values(**values)
        .execution_options(synchronize_session=False)
    )


async def discard(session: AsyncSession, message_id: UUID | None) -> None:
    """Cancel a pending row in the caller's transaction (the request was rolled back)."""
    if message_id is None:
        return
    await session.execute(
        update(OutboxMessage)
        .where(OutboxMessage.id == message_id, OutboxMessage.status == PENDING)
        .values(status=FAILED, last_error="cancelled", updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )


async def pending_count(session: AsyncSession, *, organization_id: UUID) -> int:
    rows = await session.execute(
        select(OutboxMessage.id).where(
            OutboxMessage.organization_id == organization_id, OutboxMessage.status == PENDING
        )
    )
    return len(rows.all())


def first_error(outcomes: list[PublishOutcome]) -> Exception | None:
    for outcome in outcomes:
        if outcome.error is not None:
            return outcome.error
    return None


def first_result(outcomes: list[PublishOutcome]) -> Any:
    for outcome in outcomes:
        if outcome.published:
            return outcome.result
    return None
