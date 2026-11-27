"""Beat task that flushes buffered credential usage to the database (R04-06).

Every ``USAGE_TOUCH_FLUSH_INTERVAL_SECONDS`` the task pops up to
``USAGE_TOUCH_FLUSH_BATCH_SIZE`` dirty credentials atomically (SPOP + HGETALL + DEL in one
script) and writes one max-guarded bulk UPDATE per kind. If the database write fails, the
popped touches are written back to Redis (the monotonic touch script makes that idempotent)
and the error is re-raised so Celery retries.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.usage_touch import (
    USAGE_TOUCH_FLUSHED_TOTAL,
    UsageTouch,
    UsageTouchKind,
    pop_touches,
    rebuffer_touches,
)
from app.clients.factory import create_redis_client
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import maintenance_session
from app.domains.api_keys.repositories.api_keys import ApiKeysRepository
from app.domains.service_accounts.repositories.service_accounts import (
    ServiceAccountsRepository,
)
from app.workers.async_runtime import run_async
from app.workers.base_task import RudixTask, TransientTaskError
from app.workers.celery_app import celery_app

logger = get_logger("workers.usage_touch")

_MAX_BATCHES_PER_RUN = 50

_api_keys_repository = ApiKeysRepository()
_service_accounts_repository = ServiceAccountsRepository()

# Indirections so tests can inject a fake Redis and session factory. The flush writes rows
# of every organisation, so it runs in a maintenance session (no tenant bound, excluded
# from soft-mode RLS counting, bound to DATABASE_MAINTENANCE_URL when set; R04-08).
redis_factory: Callable[[], Any] = lambda: create_redis_client(settings)  # noqa: E731
session_factory: Callable[[], Any] = maintenance_session

Rows = list[tuple[UUID, datetime, str | None]]


def _group(touches: list[UsageTouch]) -> dict[UsageTouchKind, Rows]:
    grouped: dict[UsageTouchKind, Rows] = defaultdict(list)
    for item in touches:
        grouped[item.kind].append((item.credential_id, item.used_at, item.ip_address))
    return grouped


async def _apply(session: AsyncSession, grouped: dict[UsageTouchKind, Rows]) -> None:
    if rows := grouped.get(UsageTouchKind.api_key):
        await _api_keys_repository.apply_usage_touches(session, touches=rows)
    if rows := grouped.get(UsageTouchKind.service_account_token):
        await _service_accounts_repository.apply_token_usage_touches(session, touches=rows)
    if rows := grouped.get(UsageTouchKind.service_account):
        await _service_accounts_repository.apply_account_usage_touches(session, touches=rows)


async def _flush_batch(redis: Any, batch_size: int) -> int:
    touches = await pop_touches(redis, batch_size=batch_size)
    if not touches:
        return 0
    grouped = _group(touches)
    try:
        async with session_factory() as session:
            await _apply(session, grouped)
            await session.commit()
    except Exception as exc:
        await rebuffer_touches(redis, touches)
        logger.error(
            "usage_touch.flush_failed",
            rebuffered=len(touches),
            error=exc.__class__.__name__,
        )
        raise TransientTaskError("usage touch flush failed") from exc
    for kind, rows in grouped.items():
        USAGE_TOUCH_FLUSHED_TOTAL.labels(kind=kind.value).inc(len(rows))
    return len(touches)


async def flush_usage_touches(redis: Any, *, batch_size: int | None = None) -> int:
    """Flush until the dirty set is drained (bounded per run). Returns rows flushed."""
    size = batch_size or settings.usage_touch_flush_batch_size
    flushed = 0
    for _ in range(_MAX_BATCHES_PER_RUN):
        count = await _flush_batch(redis, size)
        flushed += count
        if count < size:
            break
    if flushed:
        logger.info("usage_touch.flushed", flushed=flushed)
    return flushed


async def _flush_async() -> int:
    redis = redis_factory()
    try:
        return await flush_usage_touches(redis)
    finally:
        close = getattr(redis, "aclose", None)
        if close is not None:
            await close()


@celery_app.task(name="usage.touch.flush", bind=True, base=RudixTask, ignore_result=True)
def flush_usage_touch_task(self: RudixTask) -> int:
    """Write buffered API-key and service-account ``last_used_*`` values to the database."""
    return run_async(_flush_async())
