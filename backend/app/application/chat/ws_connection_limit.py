"""Per-user chat WebSocket connection limit (``WS_CHAT_MAX_CONNECTIONS_PER_USER``, R08-03).

Two backends, chosen by ``WS_CHAT_CONNECTION_LIMIT_BACKEND``:

- ``memory`` (default, pre-0.8.0 behaviour): a counter per user id in this process,
  guarded by an ``asyncio.Lock``. With several API replicas each counts on its own.
- ``redis``: one lease per connection in the sorted set
  ``rudix:{env}:chat:ws:conn:v1:{organization_id}:{user_id}`` (the semaphore of
  ``app/rate_limit/concurrency.py``), shared by every replica. The lease lasts
  ``WS_CHAT_CONNECTION_LEASE_SECONDS`` and the connection's heartbeat refreshes it, so a
  replica that crashed without releasing frees its slots once the lease runs out; no
  separate per-replica key is needed. ``release`` removes the lease at once (``ZREM``).

A refresh that finds the lease gone tries to take it again and never closes the socket
(log ``ws_chat.connection.lease_lost``). A Redis error on acquire follows
``RATE_LIMIT_REDIS_FAILURE_MODE``: ``open`` counts the connection in the in-process counter
instead (outcome ``fallback``), ``closed`` rejects it (the endpoint closes with ``4429``).

Only organisation and user ids and opaque lease ids are stored or logged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from app.clients import redis_client as redis_module
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.logging import get_logger
from app.core.metrics_ws import record_ws_connection_limit

logger = get_logger("chat.ws_connection_limit")

SlotBackend = Literal["memory", "redis"]

# Process-wide in-memory counters; ``app/interfaces/http/chat.py`` re-exports them as
# ``_ws_connection_counts`` / ``_ws_connection_lock`` and passes its own bindings in.
MEMORY_COUNTS: dict[str, int] = {}
MEMORY_LOCK = asyncio.Lock()


def connection_key(organization_id: str, user_id: str) -> str:
    return f"rudix:{settings.environment.value}:chat:ws:conn:v1:{organization_id}:{user_id}"


def _concurrency() -> Any:
    # Imported on use: ``app.rate_limit.concurrency`` imports the provider package, which
    # imports it back, so importing it first from here would hit a partial module.
    from app.rate_limit import concurrency

    return concurrency


def _default_redis() -> Any:
    return redis_module.redis_client


@dataclass
class WsConnectionSlot:
    """One accepted connection's slot: where it is counted and its lease id."""

    backend: SlotBackend
    organization_id: str
    user_id: str
    lease_id: str = field(default_factory=lambda: uuid4().hex)
    lease_held: bool = True
    released: bool = False


class WsConnectionLimiter:
    """Acquire, refresh, and release per-user WebSocket connection slots."""

    def __init__(
        self,
        *,
        counts: dict[str, int] | None = None,
        lock: asyncio.Lock | None = None,
        redis_getter: Callable[[], Any] = _default_redis,
        backend: SlotBackend | None = None,
    ) -> None:
        self._counts = MEMORY_COUNTS if counts is None else counts
        self._lock = MEMORY_LOCK if lock is None else lock
        self._redis_getter = redis_getter
        self._backend = backend

    @property
    def backend(self) -> SlotBackend:
        return self._backend or settings.ws_chat_connection_limit_backend

    @staticmethod
    def _limit() -> int:
        return settings.ws_chat_max_connections_per_user

    @staticmethod
    def _lease_ms() -> int:
        return settings.ws_chat_connection_lease_seconds * 1000

    async def acquire(self, *, organization_id: str, user_id: str) -> WsConnectionSlot | None:
        """Take one slot for ``user_id``; ``None`` means close with ``4429``."""
        if self.backend == "memory":
            return await self._acquire_memory(organization_id, user_id, outcome="accepted")
        slot = WsConnectionSlot("redis", organization_id, user_id)
        try:
            acquired = await self._try_acquire(slot)
        except Exception as exc:
            return await self._on_redis_error(slot, exc)
        if not acquired:
            self._rejected("redis", slot, reason="limit_reached")
            return None
        record_ws_connection_limit("redis", "accepted")
        return slot

    async def refresh(self, slot: WsConnectionSlot) -> None:
        """Heartbeat tick: extend the lease, or take it again when it is gone. Never raises."""
        if slot.backend != "redis" or slot.released:
            return
        try:
            redis = self._redis_getter()
            if redis is None:
                raise ConnectionError("redis client missing")
            key = connection_key(slot.organization_id, slot.user_id)
            if await _concurrency().try_refresh(
                redis, key=key, lease_id=slot.lease_id, lease_ms=self._lease_ms()
            ):
                slot.lease_held = True
                return
            if slot.lease_held:
                slot.lease_held = False
                record_ws_connection_limit("redis", "lease_lost")
                logger.warning(
                    "ws_chat.connection.lease_lost",
                    organization_id=slot.organization_id,
                    user_id=slot.user_id,
                )
            if await self._try_acquire(slot):
                slot.lease_held = True
                logger.info(
                    "ws_chat.connection.lease_reacquired",
                    organization_id=slot.organization_id,
                    user_id=slot.user_id,
                )
        except Exception as exc:
            logger.warning(
                "ws_chat.connection.lease_refresh_failed",
                organization_id=slot.organization_id,
                user_id=slot.user_id,
                error=exc.__class__.__name__,
            )

    async def release(self, slot: WsConnectionSlot) -> None:
        """Free the slot (idempotent). A failed ``ZREM`` leaves the lease to expire."""
        if slot.released:
            return
        slot.released = True
        if slot.backend == "memory":
            async with self._lock:
                remaining = max(0, self._counts.get(slot.user_id, 1) - 1)
                if remaining:
                    self._counts[slot.user_id] = remaining
                else:
                    self._counts.pop(slot.user_id, None)
            return
        try:
            redis = self._redis_getter()
            if redis is not None:
                key = connection_key(slot.organization_id, slot.user_id)
                await redis.zrem(key, slot.lease_id)
        except Exception as exc:
            logger.warning(
                "ws_chat.connection.release_failed",
                organization_id=slot.organization_id,
                user_id=slot.user_id,
                error=exc.__class__.__name__,
            )

    async def _try_acquire(self, slot: WsConnectionSlot) -> bool:
        redis = self._redis_getter()
        if redis is None:
            raise ConnectionError("redis client missing")
        acquired = await _concurrency().try_acquire(
            redis,
            key=connection_key(slot.organization_id, slot.user_id),
            lease_id=slot.lease_id,
            limit=self._limit(),
            lease_ms=self._lease_ms(),
        )
        return bool(acquired)

    async def _on_redis_error(
        self, slot: WsConnectionSlot, exc: BaseException
    ) -> WsConnectionSlot | None:
        mode = settings.rate_limit_redis_failure_mode
        logger.warning(
            "ws_chat.connection.limit_unavailable",
            organization_id=slot.organization_id,
            user_id=slot.user_id,
            failure_mode=mode.value,
            error=exc.__class__.__name__,
        )
        if mode == RateLimitRedisFailureMode.closed:
            self._rejected("redis", slot, reason="redis_unavailable")
            return None
        return await self._acquire_memory(slot.organization_id, slot.user_id, outcome="fallback")

    async def _acquire_memory(
        self, organization_id: str, user_id: str, *, outcome: Literal["accepted", "fallback"]
    ) -> WsConnectionSlot | None:
        metric_backend = "memory" if outcome == "accepted" else "redis"
        async with self._lock:
            current = self._counts.get(user_id, 0)
            if current >= self._limit():
                self._rejected(
                    metric_backend,
                    WsConnectionSlot("memory", organization_id, user_id),
                    reason="limit_reached",
                )
                return None
            self._counts[user_id] = current + 1
        record_ws_connection_limit(metric_backend, outcome)
        return WsConnectionSlot("memory", organization_id, user_id)

    def _rejected(self, backend: str, slot: WsConnectionSlot, *, reason: str) -> None:
        record_ws_connection_limit(backend, "rejected")
        logger.info(
            "ws_chat.connection.rejected",
            organization_id=slot.organization_id,
            user_id=slot.user_id,
            backend=backend,
            reason=reason,
            limit=self._limit(),
        )
