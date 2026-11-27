"""Beat task ``outbox.relay``: publish outbox rows the request path could not (R06-01 part 2).

Every ``OUTBOX_RELAY_INTERVAL_SECONDS`` the relay takes up to ``OUTBOX_RELAY_BATCH_SIZE``
pending rows whose ``available_at`` has passed, through ``maintenance_session()`` (rows of
every organisation), in three steps so no transaction or row lock is held while the broker
is called:

1. claim: a short transaction selects the rows ``FOR UPDATE SKIP LOCKED``, increments
   ``attempts``, and moves ``available_at`` forward by ``CLAIM_LEASE_SECONDS``, so a
   concurrent relay skips them and a relay that dies mid-batch releases them after the lease;
2. publish each claimed row outside any transaction (in a worker thread);
3. record: a second short transaction marks a published row ``published``; a failure keeps
   it ``pending`` with a backoff, or marks it ``failed`` after ``OUTBOX_MAX_ATTEMPTS``.

The record step only touches rows still ``pending`` (a request may have published the same
row meanwhile; consumers are idempotent). Only the exception class name is stored, never
broker URLs or task arguments in logs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from app.application.outbox import FAILED, PENDING, PUBLISHED, backoff_seconds, resolve_task
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_outbox_message
from app.db.session import maintenance_session
from app.models.outbox import OutboxMessage
from app.workers.async_runtime import run_async
from app.workers.base_task import RudixTask
from app.workers.celery_app import celery_app

logger = get_logger("events.outbox")

# How long a claimed row stays invisible to other relays while this one publishes it (the
# backoff cap): long enough for the broker client's publish retries, short enough that a
# relay that died mid-batch does not delay its rows for long.
CLAIM_LEASE_SECONDS = 300


@dataclass(frozen=True)
class _Claimed:
    message_id: UUID
    organization_id: UUID
    task_name: str
    kwargs: dict[str, Any]
    queue: str | None
    attempts: int


def _publish(
    task_name: str, kwargs: dict[str, Any], queue: str | None, resolver: Callable[[str], Any]
) -> Any:
    task = resolver(task_name)
    options: dict[str, Any] = {"queue": queue} if queue else {}
    return task.apply_async(kwargs=kwargs, **options)


async def _claim(session_factory: Callable[[], Any], current: datetime) -> list[_Claimed]:
    claimed: list[_Claimed] = []
    async with session_factory() as session, session.begin():
        rows = (
            await session.execute(
                select(OutboxMessage)
                .where(OutboxMessage.status == PENDING, OutboxMessage.available_at <= current)
                .order_by(OutboxMessage.available_at)
                .limit(settings.outbox_relay_batch_size)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
        for row in rows:
            row.attempts = int(row.attempts or 0) + 1
            row.available_at = current + timedelta(seconds=CLAIM_LEASE_SECONDS)
            row.updated_at = current
            claimed.append(
                _Claimed(
                    message_id=row.id,
                    organization_id=row.organization_id,
                    task_name=row.task_name,
                    kwargs=dict(row.kwargs or {}),
                    queue=row.queue,
                    attempts=row.attempts,
                )
            )
    return claimed


def _outcome_values(
    claimed: _Claimed, error: Exception | None, current: datetime
) -> tuple[str, dict[str, Any]]:
    """(counter key, column values) for one publication outcome."""
    if error is None:
        return "published", {
            "status": PUBLISHED,
            "published_at": current,
            "last_error": None,
            "updated_at": current,
        }
    values: dict[str, Any] = {"last_error": type(error).__name__[:128], "updated_at": current}
    if claimed.attempts >= settings.outbox_max_attempts:
        return "failed", {**values, "status": FAILED}
    available = current + timedelta(seconds=backoff_seconds(claimed.attempts))
    return "retried", {**values, "available_at": available}


async def relay_pending(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = maintenance_session,
    resolver: Callable[[str], Any] = resolve_task,
) -> dict[str, int]:
    current = now or datetime.now(UTC)
    counts = {"published": 0, "retried": 0, "failed": 0}
    claimed = await _claim(session_factory, current)
    if not claimed:
        return counts
    outcomes: list[tuple[_Claimed, Exception | None]] = []
    for row in claimed:
        try:
            await asyncio.to_thread(_publish, row.task_name, row.kwargs, row.queue, resolver)
        except Exception as exc:
            outcomes.append((row, exc))
            continue
        outcomes.append((row, None))
    async with session_factory() as session, session.begin():
        for row, error in outcomes:
            key, values = _outcome_values(row, error, current)
            await session.execute(
                update(OutboxMessage)
                .where(OutboxMessage.id == row.message_id, OutboxMessage.status == PENDING)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            counts[key] += 1
            if key == "published":
                record_outbox_message(row.task_name, "relayed")
            elif key == "failed":
                record_outbox_message(row.task_name, "failed")
                logger.error(
                    "outbox.relay_gave_up",
                    task_name=row.task_name,
                    message_id=str(row.message_id),
                    organization_id=str(row.organization_id),
                    attempts=row.attempts,
                    error_type=values["last_error"],
                )
    logger.info("outbox.relay_completed", **counts)
    return counts


@celery_app.task(name="outbox.relay", bind=True, base=RudixTask, ignore_result=True)
def relay_outbox(self: RudixTask) -> dict[str, int]:
    """Publish pending outbox rows (beat, every OUTBOX_RELAY_INTERVAL_SECONDS)."""
    return run_async(relay_pending())
