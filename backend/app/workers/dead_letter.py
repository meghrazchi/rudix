"""Dead-letter queue consumer (R06-05; C1).

In quorum mode a message delivered ``CELERY_DELIVERY_LIMIT`` times without an ack (a task
that keeps killing its worker, a poison payload) is dead-lettered by RabbitMQ to
``CELERY_DEAD_LETTER_EXCHANGE`` and lands in ``CELERY_DEAD_LETTER_QUEUE``. Those are Celery
task messages: a normal worker on that queue would execute them again. This consumer bootstep
reads them raw, never runs the task, records one ``FailedJob`` per task id
(``job_type='dead_letter'``, ``error_code='delivery_limit_exceeded'``), and acks.

- A message without a parseable ``organization_id`` kwarg cannot be shown to any tenant; it
  is logged and acked.
- A malformed message (not JSON, unknown body shape, no task id or name) is logged and acked,
  never requeued.
- A database error requeues the message so it is recorded once the database is back.

Enabled only where ``WORKER_CONSUME_DEAD_LETTER`` is true and ``CELERY_QUEUE_TYPE=quorum``
(the dead-letter queue does not exist in classic mode); ``python -m app.workers.pools default``
sets the flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from celery import bootsteps  # type: ignore[import-untyped]
from kombu import Consumer  # type: ignore[import-untyped]

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_dead_letter_message
from app.db.tenant_context import bind_worker_tenant
from app.workers.queues import dead_letter_queue

logger = get_logger("worker.dead_letter")

DEAD_LETTER_JOB_TYPE = "dead_letter"
DEAD_LETTER_ERROR_CODE = "delivery_limit_exceeded"
_MAX_NAME = 255
_PREFETCH = 10


class MalformedDeadLetter(ValueError):
    """The message is not a Celery task message this consumer can record."""


@dataclass(frozen=True)
class DeadLetterRecord:
    task_id: str
    task_name: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    organization_id: UUID | None = None
    document_id: UUID | None = None
    original_queue: str | None = None
    reason: str | None = None
    death_count: int = 0


def _uuid_or_none(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _bounded_str(value: Any) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned[:_MAX_NAME] if cleaned else None


def _decode_body(message: Any) -> Any:
    content_type = (getattr(message, "content_type", None) or "").lower()
    if content_type and content_type != "application/json":
        raise MalformedDeadLetter(f"unsupported content type {content_type[:64]}")
    body = getattr(message, "body", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    if not isinstance(body, str):
        raise MalformedDeadLetter("body is not text")
    try:
        return json.loads(body)
    except ValueError as exc:
        raise MalformedDeadLetter("body is not JSON") from exc


def _death_details(headers: dict[str, Any]) -> tuple[str | None, str | None, int]:
    """(original queue, reason, count) from the first ``x-death`` entry and the quorum
    ``x-delivery-count`` header, whichever count is higher."""
    queue: str | None = None
    reason: str | None = None
    count = 0
    deaths = headers.get("x-death")
    if isinstance(deaths, list) and deaths and isinstance(deaths[0], dict):
        first = deaths[0]
        queue = _bounded_str(first.get("queue"))
        reason = _bounded_str(first.get("reason"))
        raw_count = first.get("count")
        if isinstance(raw_count, int) and not isinstance(raw_count, bool):
            count = raw_count
    delivery_count = headers.get("x-delivery-count")
    if isinstance(delivery_count, int) and not isinstance(delivery_count, bool):
        count = max(count, delivery_count)
    return queue, reason, count


def parse_dead_letter(message: Any) -> DeadLetterRecord:
    """Task identity and tenant of a dead-lettered Celery message (protocol 2 or 1)."""
    headers = getattr(message, "headers", None) or {}
    if not isinstance(headers, dict):
        raise MalformedDeadLetter("headers are not a mapping")
    payload = _decode_body(message)
    task_name = _bounded_str(headers.get("task"))
    task_id = _bounded_str(headers.get("id"))
    kwargs: Any = None
    if isinstance(payload, list) and len(payload) >= 2:
        kwargs = payload[1]
    elif isinstance(payload, dict):  # protocol 1
        task_name = task_name or _bounded_str(payload.get("task"))
        task_id = task_id or _bounded_str(payload.get("id"))
        kwargs = payload.get("kwargs")
    else:
        raise MalformedDeadLetter("unknown body shape")
    if not isinstance(kwargs, dict):
        raise MalformedDeadLetter("kwargs are not a mapping")
    if task_name is None or task_id is None:
        raise MalformedDeadLetter("task name or id missing")
    queue, reason, count = _death_details(headers)
    return DeadLetterRecord(
        task_id=task_id,
        task_name=task_name,
        kwargs=kwargs,
        organization_id=_uuid_or_none(kwargs.get("organization_id")),
        document_id=_uuid_or_none(kwargs.get("document_id")),
        original_queue=queue,
        reason=reason,
        death_count=count,
    )


def _failed_job_identity(record: DeadLetterRecord) -> tuple[str, str | None, dict[str, Any]]:
    """Name, queue, and metadata a dashboard retry needs, from the task's own
    ``failed_job_identity`` when it is a registered Rudix task (stage tasks map to their
    process task), else the message's task name and original queue."""
    from app.workers.celery_app import celery_app

    task = celery_app.tasks.get(record.task_name)
    identity = getattr(task, "failed_job_identity", None)
    if callable(identity):
        name, queue, metadata = identity(dict(record.kwargs), record.original_queue)
        return str(name), queue, dict(metadata or {})
    return record.task_name, record.original_queue, {}


async def persist_dead_letter(record: DeadLetterRecord, session_factory: Any = None) -> bool:
    """Insert the FailedJob for ``record`` unless one exists for its task id; True if new."""
    from sqlalchemy import select

    from app.models.failed_job import FailedJob

    if record.organization_id is None:
        raise ValueError("dead-letter record without organization")
    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    task_name, queue_name, metadata = _failed_job_identity(record)
    metadata["dead_letter"] = {
        "task_name": record.task_name,
        "original_queue": record.original_queue,
        "reason": record.reason,
        "death_count": record.death_count,
    }
    now = datetime.now(tz=UTC)
    with bind_worker_tenant(record.organization_id):
        async with session_factory() as db:
            existing = await db.scalar(
                select(FailedJob.id)
                .where(
                    FailedJob.task_id == record.task_id,
                    FailedJob.error_code == DEAD_LETTER_ERROR_CODE,
                )
                .limit(1)
            )
            if existing is not None:
                return False
            db.add(
                FailedJob(
                    id=uuid4(),
                    organization_id=record.organization_id,
                    task_id=record.task_id,
                    task_name=task_name,
                    job_type=DEAD_LETTER_JOB_TYPE,
                    status="failed",
                    queue_name=queue_name,
                    error_code=DEAD_LETTER_ERROR_CODE,
                    error_message=(
                        "The broker dead-lettered this task after "
                        f"{record.death_count or settings.celery_delivery_limit} deliveries "
                        "without an acknowledgement; it was not executed again."
                    ),
                    attempt_count=max(record.death_count, 1),
                    is_retryable=True,
                    entity_type="document" if record.document_id else None,
                    entity_id=record.document_id,
                    metadata_json=metadata,
                    last_attempted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            await db.commit()
    return True


def handle_dead_letter(message: Any, session_factory: Any = None) -> str:
    """Record and ack one dead-lettered message; returns the outcome label."""
    from app.workers.async_runtime import run_async

    try:
        record = parse_dead_letter(message)
    except (MalformedDeadLetter, UnicodeDecodeError) as exc:
        logger.warning("dead_letter.malformed", error=str(exc)[:200])
        message.ack()
        record_dead_letter_message("malformed")
        return "malformed"
    log = {"task_name": record.task_name, "task_id": record.task_id}
    if record.organization_id is None:
        logger.warning("dead_letter.no_tenant", **log)
        message.ack()
        record_dead_letter_message("no_tenant")
        return "no_tenant"
    try:
        created = run_async(persist_dead_letter(record, session_factory))
    except Exception as exc:
        logger.error(
            "dead_letter.persist_failed",
            organization_id=str(record.organization_id),
            error_type=type(exc).__name__,
            **log,
        )
        message.requeue()
        record_dead_letter_message("error")
        return "error"
    outcome = "recorded" if created else "duplicate"
    logger.warning(
        "dead_letter.recorded" if created else "dead_letter.duplicate",
        organization_id=str(record.organization_id),
        document_id=str(record.document_id) if record.document_id else None,
        original_queue=record.original_queue,
        reason=record.reason,
        death_count=record.death_count,
        **log,
    )
    message.ack()
    record_dead_letter_message(outcome)
    return outcome


class DeadLetterConsumer(bootsteps.ConsumerStep):  # type: ignore[misc]
    """Consumes the dead-letter queue in the worker's main process without executing."""

    def include_if(self, parent: Any) -> bool:
        return bool(settings.worker_consume_dead_letter) and settings.celery_queue_type == "quorum"

    def get_consumers(self, channel: Any) -> list[Any]:
        return [
            Consumer(
                channel,
                queues=[dead_letter_queue(settings)],
                on_message=handle_dead_letter,
                prefetch_count=_PREFETCH,
                no_ack=False,
            )
        ]


class DeadLetterTopology(bootsteps.StartStopStep):  # type: ignore[misc]
    """Declares the dead-letter exchange, queue, and binding on every quorum-mode worker.

    RabbitMQ drops a dead-lettered message when its exchange routes nowhere, so the topology
    must exist wherever task queues are consumed, not only where the consumer runs.
    """

    requires = ("celery.worker.consumer:Connection",)

    def include_if(self, parent: Any) -> bool:
        return settings.celery_queue_type == "quorum"

    def start(self, parent: Any) -> None:
        channel = parent.connection.channel()
        try:
            dead_letter_queue(settings).bind(channel).declare()
            logger.info(
                "dead_letter.topology_declared",
                exchange=settings.celery_dead_letter_exchange,
                queue=settings.celery_dead_letter_queue,
            )
        finally:
            channel.close()


def install_worker_bootsteps(app: Any) -> None:
    """Add the dead-letter steps and the queue depth sampler to the consumer blueprint."""
    from app.workers.queue_metrics import QueueDepthSampler

    app.steps["consumer"].add(DeadLetterTopology)
    app.steps["consumer"].add(DeadLetterConsumer)
    app.steps["consumer"].add(QueueDepthSampler)
