"""Beat task ``outbox.relay``: publish outbox rows the request path could not (R06-01 part 2).

Every ``OUTBOX_RELAY_INTERVAL_SECONDS`` the relay takes up to ``OUTBOX_RELAY_BATCH_SIZE``
pending rows whose ``available_at`` has passed, with ``FOR UPDATE SKIP LOCKED`` so two beat
deliveries never publish the same row at once, through ``maintenance_session()`` (rows of
every organisation). A published row becomes ``published``; a failure increments
``attempts`` and backs off; after ``OUTBOX_MAX_ATTEMPTS`` the row becomes ``failed``.
Only the exception class name is stored, never broker URLs or task arguments in logs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

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


def _publish(row: OutboxMessage, resolver: Callable[[str], Any]) -> Any:
    task = resolver(row.task_name)
    options: dict[str, Any] = {"queue": row.queue} if row.queue else {}
    return task.apply_async(kwargs=dict(row.kwargs or {}), **options)


async def relay_pending(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = maintenance_session,
    resolver: Callable[[str], Any] = resolve_task,
) -> dict[str, int]:
    current = now or datetime.now(UTC)
    counts = {"published": 0, "retried": 0, "failed": 0}
    async with session_factory() as session, session.begin():
        rows = list(
            (
                await session.execute(
                    select(OutboxMessage)
                    .where(OutboxMessage.status == PENDING, OutboxMessage.available_at <= current)
                    .order_by(OutboxMessage.available_at)
                    .limit(settings.outbox_relay_batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for row in rows:
            row.attempts = int(row.attempts or 0) + 1
            row.updated_at = current
            try:
                await asyncio.to_thread(_publish, row, resolver)
            except Exception as exc:
                row.last_error = type(exc).__name__[:128]
                if row.attempts >= settings.outbox_max_attempts:
                    row.status = FAILED
                    counts["failed"] += 1
                    record_outbox_message(row.task_name, "failed")
                    logger.error(
                        "outbox.relay_gave_up",
                        task_name=row.task_name,
                        message_id=str(row.id),
                        organization_id=str(row.organization_id),
                        attempts=row.attempts,
                        error_type=row.last_error,
                    )
                else:
                    row.available_at = current + timedelta(seconds=backoff_seconds(row.attempts))
                    counts["retried"] += 1
                continue
            row.status = PUBLISHED
            row.published_at = current
            row.last_error = None
            counts["published"] += 1
            record_outbox_message(row.task_name, "relayed")
    if any(counts.values()):
        logger.info("outbox.relay_completed", **counts)
    return counts


@celery_app.task(name="outbox.relay", bind=True, base=RudixTask, ignore_result=True)
def relay_outbox(self: RudixTask) -> dict[str, int]:
    """Publish pending outbox rows (beat, every OUTBOX_RELAY_INTERVAL_SECONDS)."""
    return run_async(relay_pending())
