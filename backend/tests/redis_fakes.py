"""Shared in-memory Redis fakes (R04-07 defines, other packages extend).

``FakeRedis`` implements the commands the app uses, with an injectable millisecond clock
for expiries. ``register_script(source)`` returns an async callable ``(keys=, args=)`` that
runs the Python reference implementation registered for the script's SHA1 (the production
module defines ``reference_impl`` next to each Lua script). Unknown scripts raise, so a new
script cannot silently go untested.

Every awaited command and every script call counts one round trip in ``round_trips``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from app.application.chat.transports import resume_buffer
from app.auth import usage_touch
from app.clients.redis_scripts import ReferenceImpl, script_sha1
from app.rate_limit import concurrency, sliding_window

REFERENCE_IMPLS: dict[str, ReferenceImpl] = {
    script_sha1(sliding_window.SLIDING_WINDOW_SCRIPT): sliding_window.reference_impl,
    script_sha1(usage_touch.TOUCH_SCRIPT): usage_touch.touch_reference_impl,
    script_sha1(usage_touch.POP_SCRIPT): usage_touch.pop_reference_impl,
    script_sha1(concurrency.ACQUIRE_SCRIPT): concurrency.acquire_reference_impl,
    script_sha1(resume_buffer.APPEND_SCRIPT): resume_buffer.append_reference_impl,
}


def register_reference_impl(source: str, impl: ReferenceImpl) -> None:
    REFERENCE_IMPLS[script_sha1(source)] = impl


class FakeClock:
    """Settable millisecond clock shared by the fake and the app clock hook."""

    def __init__(self, now_ms: int) -> None:
        self.now_ms = now_ms

    def __call__(self) -> int:
        return self.now_ms

    def advance(self, milliseconds: int) -> None:
        self.now_ms += milliseconds


class _Store:
    """Synchronous keyspace implementing ``ScriptStore`` for the reference implementations."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock
        self.strings: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.lists: dict[str, list[str]] = {}
        self.expires_at_ms: dict[str, int] = {}

    def _purge(self, key: str) -> None:
        deadline = self.expires_at_ms.get(key)
        if deadline is not None and deadline <= self._clock():
            self.delete(key)

    def exists(self, key: str) -> bool:
        self._purge(key)
        return (
            key in self.strings
            or key in self.hashes
            or key in self.sets
            or key in self.zsets
            or key in self.lists
        )

    def get(self, key: str) -> str | None:
        self._purge(key)
        return self.strings.get(key)

    def set(self, key: str, value: str) -> None:
        self.strings[key] = value
        self.expires_at_ms.pop(key, None)

    def incr(self, key: str) -> int:
        value = int(self.get(key) or 0) + 1
        self.strings[key] = str(value)
        return value

    def pexpire(self, key: str, milliseconds: int) -> None:
        if self.exists(key):
            self.expires_at_ms[key] = self._clock() + milliseconds

    def pttl(self, key: str) -> int:
        if not self.exists(key):
            return -2
        deadline = self.expires_at_ms.get(key)
        return -1 if deadline is None else max(0, deadline - self._clock())

    def hget(self, key: str, field: str) -> str | None:
        self._purge(key)
        return self.hashes.get(key, {}).get(field)

    def hset(self, key: str, mapping: dict[str, str]) -> None:
        self._purge(key)
        self.hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key: str) -> dict[str, str]:
        self._purge(key)
        return dict(self.hashes.get(key, {}))

    def delete(self, key: str) -> None:
        self.strings.pop(key, None)
        self.hashes.pop(key, None)
        self.sets.pop(key, None)
        self.zsets.pop(key, None)
        self.lists.pop(key, None)
        self.expires_at_ms.pop(key, None)

    def sadd(self, key: str, member: str) -> None:
        self._purge(key)
        self.sets.setdefault(key, set()).add(member)

    def spop(self, key: str, count: int) -> list[str]:
        self._purge(key)
        members = self.sets.get(key, set())
        popped = sorted(members)[:count]
        for member in popped:
            members.discard(member)
        if not members:
            self.sets.pop(key, None)
        return popped

    # Sorted sets (R05-06).
    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self._purge(key)
        self.zsets.setdefault(key, {}).update(mapping)

    def zrem(self, key: str, member: str) -> int:
        self._purge(key)
        members = self.zsets.get(key, {})
        removed = 1 if members.pop(member, None) is not None else 0
        if not members:
            self.zsets.pop(key, None)
        return removed

    def zremrangebyscore(self, key: str, minimum: float, maximum: float) -> int:
        self._purge(key)
        members = self.zsets.get(key, {})
        doomed = [m for m, score in members.items() if minimum <= score <= maximum]
        for member in doomed:
            members.pop(member)
        if not members:
            self.zsets.pop(key, None)
        return len(doomed)

    def zcard(self, key: str) -> int:
        self._purge(key)
        return len(self.zsets.get(key, {}))

    # Lists (R05-13).
    def rpush(self, key: str, value: str) -> int:
        self._purge(key)
        items = self.lists.setdefault(key, [])
        items.append(value)
        return len(items)

    def lset(self, key: str, index: int, value: str) -> None:
        self._purge(key)
        self.lists[key][index] = value

    def llen(self, key: str) -> int:
        self._purge(key)
        return len(self.lists.get(key, []))

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        self._purge(key)
        items = self.lists.get(key, [])
        end = len(items) if stop == -1 else stop + 1
        return list(items[start:end])


class FakeRedis:
    def __init__(self, *, clock: Callable[[], int] | None = None) -> None:
        self.clock: Callable[[], int] = clock or (lambda: int(time.time() * 1000))
        self.keyspace = _Store(self.clock)
        self.round_trips = 0
        self.commands: list[str] = []
        self.script_calls: list[str] = []
        self.registered_scripts: list[str] = []

    def _count(self, command: str) -> None:
        self.round_trips += 1
        self.commands.append(command)

    async def get(self, key: str) -> str | None:
        self._count("GET")
        return self.keyspace.get(key)

    async def set(
        self, key: str, value: Any, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        self._count("SET")
        if nx and self.keyspace.exists(key):
            return None
        self.keyspace.set(key, str(value))
        if ex is not None:
            self.keyspace.pexpire(key, ex * 1000)
        return True

    async def getdel(self, key: str) -> str | None:
        self._count("GETDEL")
        value = self.keyspace.get(key)
        self.keyspace.delete(key)
        return value

    async def incr(self, key: str) -> int:
        self._count("INCR")
        return self.keyspace.incr(key)

    async def delete(self, *keys: str) -> int:
        self._count("DEL")
        removed = sum(1 for key in keys if self.keyspace.exists(key))
        for key in keys:
            self.keyspace.delete(key)
        return removed

    async def expire(self, key: str, seconds: int) -> bool:
        self._count("EXPIRE")
        exists = self.keyspace.exists(key)
        self.keyspace.pexpire(key, seconds * 1000)
        return exists

    async def pexpire(self, key: str, milliseconds: int) -> bool:
        self._count("PEXPIRE")
        exists = self.keyspace.exists(key)
        self.keyspace.pexpire(key, milliseconds)
        return exists

    async def pttl(self, key: str) -> int:
        self._count("PTTL")
        return self.keyspace.pttl(key)

    async def ttl(self, key: str) -> int:
        self._count("TTL")
        value = self.keyspace.pttl(key)
        return value if value < 0 else (value + 999) // 1000

    async def hset(self, key: str, mapping: dict[str, Any]) -> int:
        self._count("HSET")
        self.keyspace.hset(key, {field: str(value) for field, value in mapping.items()})
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        self._count("HGETALL")
        return self.keyspace.hgetall(key)

    async def sadd(self, key: str, *members: str) -> int:
        self._count("SADD")
        for member in members:
            self.keyspace.sadd(key, member)
        return len(members)

    async def spop(self, key: str, count: int = 1) -> list[str]:
        self._count("SPOP")
        return self.keyspace.spop(key, count)

    async def smembers(self, key: str) -> set[str]:
        self._count("SMEMBERS")
        self.keyspace.exists(key)
        return set(self.keyspace.sets.get(key, set()))

    async def zrem(self, key: str, *members: str) -> int:
        self._count("ZREM")
        return sum(self.keyspace.zrem(key, member) for member in members)

    async def zcard(self, key: str) -> int:
        self._count("ZCARD")
        return self.keyspace.zcard(key)

    async def rpush(self, key: str, *values: str) -> int:
        self._count("RPUSH")
        length = 0
        for value in values:
            length = self.keyspace.rpush(key, str(value))
        return length

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        self._count("LRANGE")
        return self.keyspace.lrange(key, start, stop)

    async def llen(self, key: str) -> int:
        self._count("LLEN")
        return self.keyspace.llen(key)

    async def exists(self, *keys: str) -> int:
        self._count("EXISTS")
        return sum(1 for key in keys if self.keyspace.exists(key))

    def register_script(self, source: str) -> Callable[..., Any]:
        sha = script_sha1(source)
        impl = REFERENCE_IMPLS.get(sha)
        if impl is None:
            raise AssertionError(f"no reference implementation registered for script {sha}")
        self.registered_scripts.append(sha)

        async def run(keys: Sequence[str] = (), args: Sequence[Any] = ()) -> Any:
            self._count("EVALSHA")
            self.script_calls.append(sha)
            return impl(self.keyspace, list(keys), list(args), self.clock())

        return run

    async def publish(self, channel: str, message: Any) -> int:
        """Deliver to every subscriber of ``channel`` (R06-13 agent run stream)."""
        self._count("PUBLISH")
        subscribers = list(getattr(self, "_subscribers", {}).get(channel, []))
        for subscriber in subscribers:
            subscriber.deliver(channel, str(message))
        return len(subscribers)

    def pubsub(self) -> FakePubSub:
        if not hasattr(self, "_subscribers"):
            self._subscribers: dict[str, list[FakePubSub]] = {}
        return FakePubSub(self)


class FakePubSub:
    """``redis.asyncio`` ``PubSub`` subset: subscribe, get_message, unsubscribe, aclose.

    Messages are kept in a plain list (publishers may run in another thread, as an eager
    Celery task does under ``asyncio.to_thread``); ``get_message`` polls it until timeout.
    """

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self.channels: list[str] = []
        self.messages: list[dict[str, Any]] = []
        self.closed = False

    def deliver(self, channel: str, data: str) -> None:
        self.messages.append({"type": "message", "channel": channel, "data": data})

    async def subscribe(self, *channels: str) -> None:
        self._redis._count("SUBSCRIBE")
        for channel in channels:
            self._redis._subscribers.setdefault(channel, []).append(self)
            self.channels.append(channel)

    async def get_message(
        self, ignore_subscribe_messages: bool = False, timeout: float | None = 0.0
    ) -> dict[str, Any] | None:
        del ignore_subscribe_messages
        import asyncio

        waited = 0.0
        while not self.messages:
            if timeout is None or waited >= timeout:
                return None
            await asyncio.sleep(0.005)
            waited += 0.005
        return self.messages.pop(0)

    async def unsubscribe(self, *channels: str) -> None:
        for channel in channels or tuple(self.channels):
            subscribers = self._redis._subscribers.get(channel, [])
            if self in subscribers:
                subscribers.remove(self)
        self.channels = [channel for channel in self.channels if channel not in channels]
        if not channels:
            self.channels = []

    async def aclose(self) -> None:
        self.closed = True


class BrokenRedis:
    """Every command raises, like a Redis that is down mid-request."""

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)

        def broken(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            if name == "register_script":

                async def run(*a: Any, **k: Any) -> Any:
                    del a, k
                    raise ConnectionError("redis unavailable")

                return run
            raise ConnectionError("redis unavailable")

        async def broken_async(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            raise ConnectionError("redis unavailable")

        return broken if name == "register_script" else broken_async


def align_app_clock(monkeypatch: Any, clock: Callable[[], int]) -> None:
    """Make the limiter's app clock (window index) follow the fake Redis clock."""
    monkeypatch.setattr(sliding_window, "now_ms", clock)
