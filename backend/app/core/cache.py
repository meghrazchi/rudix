"""Application cache with organisation- and user-versioned keys (R04-05).

Values live under ``rudix:{env}:org:{org_id}:v{version}:{namespace}:{id}`` or
``rudix:{env}:user:{user_id}:v{version}:{namespace}:{id}``. Invalidation never deletes value
keys: it increments the scope's version key (see ``app.core.cache_invalidation``), which
orphans every value written under the old version. ``get_or_load`` reads the version
*before* calling the loader and writes under that version, so a slow writer that loaded
stale rows can only write an orphaned key.

Every organisation-scoped namespace carries the organisation id in the key, so a value is
never shared across organisations. Any Redis failure, a missing client, or the
``CACHE_ENABLED`` kill switch falls back to the loader (the database).

Redis roles (R08-05): version keys always live on ``REDIS_URL`` (``redis_client``); values
go to ``REDIS_CACHE_URL`` (``cache_redis_client``) when it is set, else to ``REDIS_URL``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Final
from uuid import UUID

from prometheus_client import Counter
from pydantic import TypeAdapter, ValidationError

from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import registry

logger = get_logger("core.cache")

CACHE_HITS_TOTAL = Counter(
    "rudix_cache_hits_total",
    "Application cache hits by namespace",
    ["namespace"],
    registry=registry,
)
CACHE_MISSES_TOTAL = Counter(
    "rudix_cache_misses_total",
    "Application cache misses (value loaded from the database) by namespace",
    ["namespace"],
    registry=registry,
)
CACHE_ERRORS_TOTAL = Counter(
    "rudix_cache_errors_total",
    "Application cache fallbacks to the database by namespace and failed operation",
    ["namespace", "operation"],
    registry=registry,
)
CACHE_INVALIDATIONS_TOTAL = Counter(
    "rudix_cache_invalidations_total",
    "Post-commit cache version bumps by scope and result",
    ["scope", "result"],
    registry=registry,
)

# Namespaces cached in 0.4.0. AI policy, RAG/model profiles, tool and quota policy: 0.5.0.
NAMESPACE_AUTH_PRINCIPAL: Final = "auth_principal"
NAMESPACE_PERMISSION_SET: Final = "permission_set"
NAMESPACE_FEATURE_FLAGS: Final = "feature_flags"


@dataclass(frozen=True)
class OrgScope:
    org_id: UUID | str

    kind: ClassVar[str] = "org"

    @property
    def scope_id(self) -> str:
        return str(self.org_id)


@dataclass(frozen=True)
class UserScope:
    user_id: UUID | str

    kind: ClassVar[str] = "user"

    @property
    def scope_id(self) -> str:
        return str(self.user_id)


CacheScope = OrgScope | UserScope

# Leader futures per value key (in-process single-flight). The value is the loaded result,
# or ``_LEADER_FAILED`` when the leader raised, so followers fall back to their own loader.
_LEADER_FAILED: Final = object()
_inflight: dict[str, asyncio.Future[Any]] = {}


def now_ms() -> int:
    return int(time.time() * 1000)


def _prefix() -> str:
    return f"rudix:{settings.environment.value}"


def version_key(kind: str, scope_id: str) -> str:
    return f"{_prefix()}:{kind}:{scope_id}:version"


def value_key(scope: CacheScope, version: int, namespace: str, key_id: str) -> str:
    return f"{_prefix()}:{scope.kind}:{scope.scope_id}:v{version}:{namespace}:{key_id}"


def value_redis_client() -> Any:
    """The client for cached values: ``REDIS_CACHE_URL``'s when set, else ``REDIS_URL``'s.

    Version keys never use it (``_current_version`` and ``cache_invalidation._bump`` read
    ``redis_client``), so evicting cached values cannot reset a version.
    """
    return redis_module.cache_redis_client or redis_module.redis_client


def _timeout_seconds() -> float:
    return settings.cache_operation_timeout_ms / 1000


def record_error(namespace: str, operation: str, exc: BaseException | None = None) -> None:
    CACHE_ERRORS_TOTAL.labels(namespace=namespace, operation=operation).inc()
    if exc is not None:
        logger.warning(
            "cache.fallback",
            namespace=namespace,
            operation=operation,
            error=exc.__class__.__name__,
        )


async def _call(awaitable: Awaitable[Any]) -> Any:
    return await asyncio.wait_for(awaitable, timeout=_timeout_seconds())


async def _current_version(client: Any, kind: str, scope_id: str) -> int:
    """Return the scope version, initialising a missing key from the millisecond clock.

    A fresh epoch-millisecond value is never a version used before an eviction (old
    versions were initialised earlier and bumped once per invalidation), so an evicted
    version key cannot resurrect orphaned values.
    """
    key = version_key(kind, scope_id)
    raw = await _call(client.get(key))
    if raw is not None:
        return int(raw)
    initial = now_ms()
    created = await _call(client.set(key, initial, nx=True))
    if created:
        return initial
    raw = await _call(client.get(key))
    return int(raw) if raw is not None else initial


async def _load_and_store[T](
    *,
    client: Any,
    key: str,
    namespace: str,
    ttl: int,
    adapter: TypeAdapter[T],
    loader: Callable[[], Awaitable[T]],
) -> T:
    try:
        raw = await _call(client.get(key))
    except Exception as exc:
        record_error(namespace, "get", exc)
        return await loader()
    if raw is not None:
        try:
            value = adapter.validate_json(raw)
        except ValidationError as exc:
            record_error(namespace, "decode", exc)
        else:
            CACHE_HITS_TOTAL.labels(namespace=namespace).inc()
            return value
    CACHE_MISSES_TOTAL.labels(namespace=namespace).inc()
    value = await loader()
    try:
        await _call(client.set(key, adapter.dump_json(value).decode("utf-8"), ex=ttl))
    except Exception as exc:
        record_error(namespace, "set", exc)
    return value


async def get_or_load[T](
    *,
    scope: CacheScope,
    namespace: str,
    key_id: str,
    ttl: int,
    adapter: TypeAdapter[T],
    loader: Callable[[], Awaitable[T]],
) -> T:
    """Return the cached value for ``(scope, namespace, key_id)`` or load and cache it.

    Exceptions raised by ``loader`` propagate and nothing is cached for them.
    """
    if not settings.cache_enabled:
        record_error(namespace, "disabled")
        return await loader()
    # R08-05: versions live with the state (REDIS_URL) so a cache eviction can never reset
    # one; values go to REDIS_CACHE_URL when it is configured.
    client = redis_module.redis_client
    if client is None:
        record_error(namespace, "unavailable")
        return await loader()
    try:
        version = await _current_version(client, scope.kind, scope.scope_id)
    except Exception as exc:
        record_error(namespace, "version", exc)
        return await loader()
    value_client = value_redis_client()

    key = value_key(scope, version, namespace, key_id)
    leader = _inflight.get(key)
    if leader is not None:
        result = await asyncio.shield(leader)
        if result is _LEADER_FAILED:
            return await loader()
        CACHE_HITS_TOTAL.labels(namespace=namespace).inc()
        return result  # type: ignore[no-any-return]

    future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    _inflight[key] = future
    try:
        value = await _load_and_store(
            client=value_client,
            key=key,
            namespace=namespace,
            ttl=ttl,
            adapter=adapter,
            loader=loader,
        )
    except BaseException:
        future.set_result(_LEADER_FAILED)
        raise
    else:
        future.set_result(value)
        return value
    finally:
        if _inflight.get(key) is future:
            del _inflight[key]
