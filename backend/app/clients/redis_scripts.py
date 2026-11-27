"""Registered Lua scripts on a Redis client, cached once per client object.

``redis.register_script`` returns a script object whose call runs ``EVALSHA`` and falls
back to ``SCRIPT LOAD`` + ``EVALSHA`` on ``NOSCRIPT``, so a warm call is one round trip.
The script object is cached on the client so every request reuses it.

Each production script ships a Python ``reference_impl`` with the same semantics. The test
fake (``tests/redis_fakes.py``) dispatches ``register_script`` to it by the SHA1 of the
script source; a ``requires_redis`` test compares both against a real server.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

_CACHE_ATTRIBUTE = "_rudix_registered_scripts"

ScriptCallable = Callable[..., Awaitable[Any]]


class ScriptStore(Protocol):
    """Synchronous view of a Redis keyspace used by the Python reference implementations."""

    def get(self, key: str) -> str | None: ...

    def incr(self, key: str) -> int: ...

    def pexpire(self, key: str, milliseconds: int) -> None: ...

    def hget(self, key: str, field: str) -> str | None: ...

    def hset(self, key: str, mapping: dict[str, str]) -> None: ...

    def hgetall(self, key: str) -> dict[str, str]: ...

    def delete(self, key: str) -> None: ...

    def sadd(self, key: str, member: str) -> None: ...

    def spop(self, key: str, count: int) -> list[str]: ...


ReferenceImpl = Callable[[ScriptStore, Sequence[str], Sequence[Any], int], Any]


def script_sha1(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def get_script(redis: Any, source: str) -> ScriptCallable:
    """Return the registered script for ``source`` on ``redis``, registering it once."""
    cache = getattr(redis, _CACHE_ATTRIBUTE, None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(redis, _CACHE_ATTRIBUTE, cache)
    sha = script_sha1(source)
    script = cache.get(sha)
    if script is None:
        script = redis.register_script(source)
        cache[sha] = script
    return script  # type: ignore[no-any-return]


def as_text(value: Any) -> str:
    """Decode a Redis reply element that may be ``bytes`` (clients without decoding)."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
