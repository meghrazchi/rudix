"""Per-organisation concurrency limit for LLM calls: a Redis semaphore (R05-06).

One sorted set per organisation holds the lease ids of the calls in flight, scored by their
expiry (Redis ``TIME`` plus ``LLM_ORG_SEMAPHORE_LEASE_SECONDS``). ``ACQUIRE_SCRIPT`` purges
expired leases, then adds the new lease only while fewer than ``limit`` remain, in one round
trip. A call releases its lease by id (``ZREM``); a lease of a crashed worker expires.

The key carries the organisation as its cluster hash tag:
``rudix:{env}:llm:concurrency:v1:{org:<id>}``. Only organisation ids and opaque lease ids
are stored.

Failure mode: no organisation in the tenant context (workers, scripts) means no limit;
``LLM_ORG_MAX_CONCURRENT_CALLS=0`` (the default) disables it; a missing or failing Redis
admits the call and counts ``rudix_llm_org_semaphore_unavailable_total`` (fail open). When
the limit stays reached for ``LLM_ORG_SEMAPHORE_WAIT_MS`` the call raises
``ProviderBusyError`` (WebSocket ``provider_busy``, HTTP 429 ``{"code": "provider_busy"}``).

A stream that outlives its lease (``LLM_ORG_SEMAPHORE_LEASE_SECONDS``, 120 s by default) is
no longer counted; the lease is not renewed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from app.clients import redis_client as redis_module
from app.clients.redis_scripts import ScriptStore, get_script
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    LLM_ORG_CONCURRENCY_REJECTED_TOTAL,
    LLM_ORG_SEMAPHORE_UNAVAILABLE_TOTAL,
)
from app.db.tenant_context import get_current_tenant_id
from app.domains.ai.providers.errors import ProviderError

logger = get_logger("rate_limit.concurrency")

ACQUIRE_SCRIPT = """
local limit = tonumber(ARGV[2])
local lease_ms = tonumber(ARGV[3])
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  return {0, count}
end
redis.call('ZADD', KEYS[1], now_ms + lease_ms, ARGV[1])
redis.call('PEXPIRE', KEYS[1], lease_ms)
return {1, count + 1}
"""

# Interval between two acquire attempts while waiting for a slot.
_POLL_SECONDS = 0.05


class ProviderBusyError(ProviderError):
    """The organisation's concurrent LLM call limit stayed reached for the wait time."""


def acquire_reference_impl(
    store: ScriptStore, keys: Sequence[str], args: Sequence[Any], now_ms: int
) -> list[int]:
    """Python twin of ``ACQUIRE_SCRIPT`` (``now_ms`` stands in for Redis ``TIME``)."""
    key = keys[0]
    lease_id = str(args[0])
    limit, lease_ms = int(args[1]), int(args[2])
    store.zremrangebyscore(key, float("-inf"), float(now_ms))
    count = store.zcard(key)
    if count >= limit:
        return [0, count]
    store.zadd(key, {lease_id: float(now_ms + lease_ms)})
    store.pexpire(key, lease_ms)
    return [1, count + 1]


def semaphore_key(organization_id: UUID | str) -> str:
    return f"rudix:{settings.environment.value}:llm:concurrency:v1:{{org:{organization_id}}}"


async def try_acquire(redis: Any, *, key: str, lease_id: str, limit: int, lease_ms: int) -> bool:
    """One acquire attempt (one round trip). Redis errors propagate."""
    script = get_script(redis, ACQUIRE_SCRIPT)
    reply = await script(keys=[key], args=[lease_id, limit, lease_ms])
    return int(reply[0]) == 1


async def acquire(
    redis: Any, *, key: str, lease_id: str, limit: int, lease_ms: int, wait_ms: int
) -> bool:
    """Acquire a lease, retrying every 50 ms for up to ``wait_ms``; False when still full."""
    deadline = time.monotonic() + max(0, wait_ms) / 1000
    while True:
        if await try_acquire(redis, key=key, lease_id=lease_id, limit=limit, lease_ms=lease_ms):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(_POLL_SECONDS, remaining))


def _unavailable(organization_id: UUID, reason: str) -> None:
    LLM_ORG_SEMAPHORE_UNAVAILABLE_TOTAL.inc()
    logger.warning(
        "llm.org_semaphore.unavailable",
        organization_id=str(organization_id),
        reason=reason,
    )


async def _release(redis: Any, key: str, lease_id: str, organization_id: UUID) -> None:
    try:
        await redis.zrem(key, lease_id)
    except Exception as exc:  # the lease expires on its own
        logger.warning(
            "llm.org_semaphore.release_failed",
            organization_id=str(organization_id),
            error=exc.__class__.__name__,
        )


@asynccontextmanager
async def org_call_slot(provider_key: str) -> AsyncIterator[None]:
    """Hold one of the organisation's LLM call slots for the body (see module docstring)."""
    limit = settings.llm_org_max_concurrent_calls
    organization_id = get_current_tenant_id()
    if limit <= 0 or organization_id is None:
        yield
        return
    redis = redis_module.redis_client
    if redis is None:
        _unavailable(organization_id, "redis_missing")
        yield
        return
    key = semaphore_key(organization_id)
    lease_id = uuid4().hex
    acquired: bool | None
    try:
        acquired = await acquire(
            redis,
            key=key,
            lease_id=lease_id,
            limit=limit,
            lease_ms=settings.llm_org_semaphore_lease_seconds * 1000,
            wait_ms=settings.llm_org_semaphore_wait_ms,
        )
    except Exception:
        acquired = None
    if acquired is None:
        _unavailable(organization_id, "redis_error")
        yield
        return
    if not acquired:
        LLM_ORG_CONCURRENCY_REJECTED_TOTAL.inc()
        logger.info(
            "llm.org_semaphore.rejected",
            organization_id=str(organization_id),
            provider=provider_key,
            limit=limit,
            wait_ms=settings.llm_org_semaphore_wait_ms,
        )
        raise ProviderBusyError("The organisation's concurrent LLM call limit is reached")
    try:
        yield
    finally:
        await _release(redis, key, lease_id, organization_id)
