"""Publish realtime events after commit (R07-07).

``record_realtime_event(session, event)`` stores the event in ``session.info``;
``after_commit`` publishes every recorded event synchronously through
``sqlalchemy.util.await_only`` (the pattern of ``app/core/cache_invalidation.py``), so a
rolled-back transaction publishes nothing and ``await session.commit()`` returns after
Redis was written. ``publish_now(event)`` is for code without a session (the agent run
event sink, which already publishes after its own commits).

Per event: ``INCR`` the organisation's sequence (the event id; the counter never expires so
ids keep increasing for reconnecting clients), ``RPUSH`` the entry to the replay buffer,
``LTRIM`` it to ``REALTIME_BUFFER_MAX_EVENTS``, ``PEXPIRE`` the buffer to
``REALTIME_BUFFER_TTL_SECONDS``, and ``PUBLISH`` it on the organisation channel.

Redis is the API's client (``app.clients.redis_client.redis_client``); a Celery worker
process (``use_worker_redis()`` from ``worker_process_init``) creates its own client lazily,
one per event loop. Any failure is logged with the event type and organisation id only,
counted in ``rudix_realtime_events_published_total{outcome}``, and never raised: a status
transition never fails because of a realtime hint. Events are hints; a worker retry may
publish the same transition twice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import MissingGreenlet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction
from sqlalchemy.util import await_only

from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_realtime import record_realtime_published
from app.domains.realtime.events import (
    RealtimeEvent,
    buffer_key,
    channel_name,
    sequence_key,
)

logger = get_logger("realtime.publisher")

PENDING_INFO_KEY = "rudix_realtime_pending_events"

_installed = False
_worker_mode = False
_worker_client: tuple[asyncio.AbstractEventLoop, Any] | None = None


def use_worker_redis(enabled: bool = True) -> None:
    """Called once per Celery worker process: publish through a process-local client."""
    global _worker_mode, _worker_client
    _worker_mode = enabled
    _worker_client = None


def _worker_redis() -> Any:
    global _worker_client
    loop = asyncio.get_running_loop()
    if _worker_client is not None and _worker_client[0] is loop:
        return _worker_client[1]
    from app.clients.factory import create_redis_client

    client = create_redis_client(settings)
    _worker_client = (loop, client)
    return client


def _redis() -> Any:
    client = redis_module.redis_client
    if client is not None or not _worker_mode:
        return client
    try:
        return _worker_redis()
    except Exception as exc:
        logger.warning("realtime.redis_unavailable", error=exc.__class__.__name__)
        return None


def _sync_session(session: Session | AsyncSession) -> Session:
    return session.sync_session if isinstance(session, AsyncSession) else session


def record_realtime_event(
    session: Session | AsyncSession, events: RealtimeEvent | Iterable[RealtimeEvent]
) -> None:
    """Publish ``events`` when ``session`` commits; nothing when realtime is disabled."""
    if not settings.realtime_events_enabled:
        return
    batch = [events] if isinstance(events, RealtimeEvent) else list(events)
    if not batch:
        return
    install_realtime_listeners()
    pending: list[RealtimeEvent] = _sync_session(session).info.setdefault(PENDING_INFO_KEY, [])
    pending.extend(batch)


def _log_failure(item: RealtimeEvent, outcome: str, error: str | None = None) -> None:
    record_realtime_published(item.type, outcome)
    logger.warning(
        "realtime.publish_failed",
        event_type=item.type,
        organization_id=item.organization_id,
        outcome=outcome,
        error=error,
    )


async def _publish_one(client: Any, item: RealtimeEvent) -> None:
    list_key = buffer_key(item.organization_id)
    try:
        event_id = int(await client.incr(sequence_key(item.organization_id)))
        entry = item.to_entry(event_id)
        await client.rpush(list_key, entry)
        await client.ltrim(list_key, -settings.realtime_buffer_max_events, -1)
        await client.pexpire(list_key, settings.realtime_buffer_ttl_seconds * 1000)
        await client.publish(channel_name(item.organization_id), entry)
    except Exception as exc:
        _log_failure(item, "failed", exc.__class__.__name__)
        return
    record_realtime_published(item.type, "published")


async def publish_events(events: Iterable[RealtimeEvent], *, redis: Any = None) -> None:
    """Publish in order; never raises."""
    batch = list(events)
    if not batch or not settings.realtime_events_enabled:
        return
    client = redis if redis is not None else _redis()
    if client is None:
        for item in batch:
            _log_failure(item, "unavailable")
        return
    for item in batch:
        await _publish_one(client, item)


async def publish_now(event: RealtimeEvent | Iterable[RealtimeEvent], *, redis: Any = None) -> None:
    """Publish immediately (no transaction to wait for); never raises."""
    await publish_events([event] if isinstance(event, RealtimeEvent) else event, redis=redis)


def _after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return  # a SAVEPOINT release is not a commit
    pending: list[RealtimeEvent] | None = session.info.pop(PENDING_INFO_KEY, None)
    if not pending:
        return
    coroutine = publish_events(pending)
    try:
        await_only(coroutine)
    except MissingGreenlet:
        coroutine.close()
        for item in pending:
            record_realtime_published(item.type, "skipped")
        logger.warning("realtime.publish_skipped", reason="no_async_context", count=len(pending))
    except Exception as exc:  # pragma: no cover - publish_events never raises
        logger.warning("realtime.publish_failed", error=exc.__class__.__name__)


def _after_rollback(session: Session) -> None:
    if session.in_nested_transaction():
        return  # ROLLBACK TO SAVEPOINT: the outer transaction may still commit
    session.info.pop(PENDING_INFO_KEY, None)


def _after_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None and not transaction.nested:
        session.info.pop(PENDING_INFO_KEY, None)


def install_realtime_listeners() -> None:
    """Register the Session listeners once per process (idempotent)."""
    global _installed
    if _installed:
        return
    from app.application.realtime.observers import after_flush

    event.listen(Session, "after_flush", after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    event.listen(Session, "after_transaction_end", _after_transaction_end)
    _installed = True
