"""Chat WebSocket connection limit across replicas (R08-03).

Two ``WsConnectionLimiter`` instances with their own in-process counters stand for two API
replicas sharing one Redis (``FakeRedis``, the acquire and refresh scripts run through their
Python reference implementations). ``BrokenRedis`` is a Redis that is down; under
``requires_redis`` the Lua scripts run against a real server (``TEST_REDIS_URL``).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import WebSocketDisconnect
from pydantic import ValidationError

from app.application.chat import ws_connection_limit as limit_module
from app.application.chat.ws_auth import WsAuthResult
from app.application.chat.ws_connection_limit import (
    WsConnectionLimiter,
    WsConnectionSlot,
    connection_key,
)
from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core import metrics_infra
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.metrics_ws import CHAT_WS_CONNECTION_LIMIT_TOTAL
from app.core.settings.deployment import DeploymentSettings
from app.core.settings.features import FeaturesSettings
from app.interfaces.http import chat as chat_api
from app.rate_limit import concurrency
from tests.redis_fakes import BrokenRedis, FakeClock, FakeRedis

ORG = "org-1"
USER = "user-1"
LEASE_MS = 90_000


def _count(backend: str, outcome: str) -> float:
    return float(
        CHAT_WS_CONNECTION_LIMIT_TOTAL.labels(backend=backend, outcome=outcome)._value.get()
    )


def _gauge() -> float:
    return float(metrics_infra.CHAT_WS_CONNECTIONS._value.get())


@pytest.fixture(autouse=True)
def _limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "ws_chat_max_connections_per_user", 2)
    monkeypatch.setattr(settings, "ws_chat_connection_lease_seconds", LEASE_MS // 1000)
    monkeypatch.setattr(settings, "ws_chat_connection_limit_backend", "redis")
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.open)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(5_000_000)


@pytest.fixture
def shared_redis(clock: FakeClock) -> FakeRedis:
    return FakeRedis(clock=clock)


def _replica(redis: Any) -> WsConnectionLimiter:
    """One API replica: its own in-process counter and lock, the shared Redis."""
    return WsConnectionLimiter(counts={}, lock=asyncio.Lock(), redis_getter=lambda: redis)


async def _take(limiter: WsConnectionLimiter) -> WsConnectionSlot | None:
    return await limiter.acquire(organization_id=ORG, user_id=USER)


# -- limiter --------------------------------------------------------------------------------


async def test_two_replicas_enforce_the_limit_together(shared_redis: FakeRedis) -> None:
    replica_a, replica_b = _replica(shared_redis), _replica(shared_redis)
    accepted, rejected = _count("redis", "accepted"), _count("redis", "rejected")

    first = await _take(replica_a)
    second = await _take(replica_b)
    assert first is not None and second is not None
    assert first.backend == second.backend == "redis"
    assert await _take(replica_a) is None
    assert await _take(replica_b) is None
    # Another user of the organisation has their own slots.
    other = await replica_a.acquire(organization_id=ORG, user_id="user-2")
    assert other is not None

    assert shared_redis.keyspace.zcard(connection_key(ORG, USER)) == 2
    assert _count("redis", "accepted") - accepted == 3
    assert _count("redis", "rejected") - rejected == 2


async def test_release_frees_the_slot_at_once(shared_redis: FakeRedis) -> None:
    replica_a, replica_b = _replica(shared_redis), _replica(shared_redis)
    first = await _take(replica_a)
    assert first is not None and await _take(replica_b) is not None
    assert await _take(replica_b) is None

    await replica_a.release(first)
    await replica_a.release(first)  # idempotent
    assert await _take(replica_b) is not None


async def test_crashed_replica_frees_its_slots_after_the_lease(
    shared_redis: FakeRedis, clock: FakeClock
) -> None:
    crashed, alive = _replica(shared_redis), _replica(shared_redis)
    assert await _take(crashed) is not None
    kept = await _take(alive)
    assert kept is not None
    assert await _take(alive) is None

    # The live replica refreshes on each heartbeat; the crashed one never does.
    for _ in range(4):
        clock.advance(30_000)
        await alive.refresh(kept)
        assert kept.lease_held
    assert clock.now_ms - 5_000_000 > LEASE_MS
    assert await _take(alive) is not None
    assert shared_redis.keyspace.zcard(connection_key(ORG, USER)) == 2


async def test_refresh_extends_the_lease_from_redis_time(
    shared_redis: FakeRedis, clock: FakeClock
) -> None:
    limiter = _replica(shared_redis)
    slot = await _take(limiter)
    assert slot is not None
    clock.advance(30_000)
    await limiter.refresh(slot)
    score = shared_redis.keyspace.zscore(connection_key(ORG, USER), slot.lease_id)
    assert score == clock.now_ms + LEASE_MS
    assert shared_redis.keyspace.pttl(connection_key(ORG, USER)) == LEASE_MS


async def test_lost_lease_is_reacquired_and_never_closes(
    shared_redis: FakeRedis, clock: FakeClock
) -> None:
    limiter = _replica(shared_redis)
    slot = await _take(limiter)
    assert slot is not None
    lost = _count("redis", "lease_lost")

    clock.advance(LEASE_MS + 1)  # e.g. a long event-loop stall: the lease expired
    await limiter.refresh(slot)
    assert slot.lease_held
    assert _count("redis", "lease_lost") - lost == 1
    assert shared_redis.keyspace.zscore(connection_key(ORG, USER), slot.lease_id) is not None


async def test_lost_lease_while_full_keeps_retrying(shared_redis: FakeRedis) -> None:
    limiter, other = _replica(shared_redis), _replica(shared_redis)
    slot = await _take(limiter)
    assert slot is not None
    await shared_redis.zrem(connection_key(ORG, USER), slot.lease_id)  # lease gone
    assert await _take(other) is not None and await _take(other) is not None
    lost = _count("redis", "lease_lost")

    await limiter.refresh(slot)
    await limiter.refresh(slot)  # still full: counted once, socket stays open
    assert not slot.lease_held
    assert _count("redis", "lease_lost") - lost == 1

    await shared_redis.delete(connection_key(ORG, USER))
    await limiter.refresh(slot)
    assert slot.lease_held


async def test_refresh_skips_memory_and_released_slots(shared_redis: FakeRedis) -> None:
    limiter = _replica(shared_redis)
    memory_slot = WsConnectionSlot("memory", ORG, USER)
    await limiter.refresh(memory_slot)
    released = WsConnectionSlot("redis", ORG, USER, released=True)
    await limiter.refresh(released)
    assert shared_redis.script_calls == []


async def test_refresh_and_release_survive_a_broken_redis() -> None:
    limiter = _replica(BrokenRedis())
    slot = WsConnectionSlot("redis", ORG, USER)
    await limiter.refresh(slot)  # logged, not raised
    await limiter.release(slot)
    assert slot.released
    missing = WsConnectionLimiter(counts={}, lock=asyncio.Lock(), redis_getter=lambda: None)
    await missing.refresh(WsConnectionSlot("redis", ORG, USER))


async def test_broken_redis_open_mode_falls_back_to_memory_counter() -> None:
    limiter = _replica(BrokenRedis())
    fallback = _count("redis", "fallback")
    first, second = await _take(limiter), await _take(limiter)
    assert first is not None and second is not None
    assert first.backend == "memory"
    assert await _take(limiter) is None  # the in-process counter still enforces the limit
    assert _count("redis", "fallback") - fallback == 2
    await limiter.release(first)
    assert await _take(limiter) is not None


async def test_missing_redis_client_follows_the_failure_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = WsConnectionLimiter(counts={}, lock=asyncio.Lock(), redis_getter=lambda: None)
    slot = await _take(limiter)
    assert slot is not None and slot.backend == "memory"
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.closed)
    assert await _take(limiter) is None


async def test_broken_redis_closed_mode_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.closed)
    rejected = _count("redis", "rejected")
    assert await _take(_replica(BrokenRedis())) is None
    assert _count("redis", "rejected") - rejected == 1


async def test_memory_backend_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ws_chat_connection_limit_backend", "memory")
    redis = FakeRedis()
    counts: dict[str, int] = {}
    limiter = WsConnectionLimiter(counts=counts, lock=asyncio.Lock(), redis_getter=lambda: redis)
    accepted = _count("memory", "accepted")
    first, second = await _take(limiter), await _take(limiter)
    assert first is not None and second is not None
    assert counts == {USER: 2}
    assert await _take(limiter) is None
    await limiter.refresh(first)
    await limiter.release(first)
    assert counts == {USER: 1}
    await limiter.release(second)
    assert counts == {}
    assert redis.round_trips == 0
    assert _count("memory", "accepted") - accepted == 2


async def test_default_limiter_uses_the_module_counter_and_client(
    monkeypatch: pytest.MonkeyPatch, shared_redis: FakeRedis
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", shared_redis)
    limiter = WsConnectionLimiter()
    assert limiter.backend == "redis"
    slot = await _take(limiter)
    assert slot is not None and shared_redis.keyspace.zcard(connection_key(ORG, USER)) == 1
    await limiter.release(slot)
    assert WsConnectionLimiter(backend="memory").backend == "memory"
    assert limit_module.MEMORY_COUNTS is chat_api._ws_connection_counts
    assert limit_module.MEMORY_LOCK is chat_api._ws_connection_lock


def test_connection_key_carries_environment_organisation_and_user() -> None:
    assert connection_key("o", "u") == f"rudix:{settings.environment.value}:chat:ws:conn:v1:o:u"


class _HeartbeatProbe(FeaturesSettings, DeploymentSettings):
    pass


def test_lease_must_exceed_two_heartbeats() -> None:
    assert _HeartbeatProbe().ws_chat_connection_lease_seconds == 90
    with pytest.raises(ValidationError, match="greater than twice"):
        _HeartbeatProbe(ws_chat_heartbeat_interval_seconds=45, ws_chat_connection_lease_seconds=90)
    assert DeploymentSettings(ws_chat_connection_lease_seconds=10).api_shutdown_drain_seconds == 0


def test_settings_defaults_keep_the_memory_backend() -> None:
    assert type(settings).model_fields["ws_chat_connection_limit_backend"].default == "memory"


# -- chat WebSocket endpoint ----------------------------------------------------------------


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=USER, organization_id=ORG, roles=["member"], auth_provider="test"
    )


class _HeldSocket:
    """Stays connected until ``hang_up`` is set; records accept and close."""

    def __init__(self, *, accept_error: BaseException | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.client = None
        self.accepted = asyncio.Event()
        self.hang_up = asyncio.Event()
        self.close_code: int | None = None
        self.sent: list[dict[str, Any]] = []
        self._accept_error = accept_error

    async def accept(self) -> None:
        if self._accept_error is not None:
            raise self._accept_error
        self.accepted.set()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        del reason
        self.close_code = code

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        await self.hang_up.wait()
        raise WebSocketDisconnect()


@pytest_asyncio.fixture
async def ws_endpoint(
    monkeypatch: pytest.MonkeyPatch, shared_redis: FakeRedis
) -> AsyncIterator[Callable[[_HeldSocket], asyncio.Task[None]]]:
    async def fake_auth(**kwargs: Any) -> WsAuthResult:
        del kwargs
        return WsAuthResult(principal=_principal(), method="ticket")

    monkeypatch.setattr(settings, "feature_chat_websocket_enabled", True)
    monkeypatch.setattr(chat_api, "authenticate_ws_handshake", fake_auth)
    monkeypatch.setattr(redis_module, "redis_client", shared_redis)
    monkeypatch.setattr(chat_api, "_ws_connection_counts", {})
    monkeypatch.setattr(chat_api, "_ws_connection_lock", asyncio.Lock())
    tasks: list[asyncio.Task[None]] = []

    def connect(socket: _HeldSocket) -> asyncio.Task[None]:
        task = asyncio.create_task(chat_api.chat_websocket(socket, ticket="t"))  # type: ignore[arg-type]
        tasks.append(task)
        return task

    yield connect
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_endpoint_counts_a_slot_held_on_another_instance(
    ws_endpoint: Callable[[_HeldSocket], asyncio.Task[None]], shared_redis: FakeRedis
) -> None:
    other_instance = _replica(shared_redis)
    remote = await _take(other_instance)
    assert remote is not None
    gauge = _gauge()

    held = _HeldSocket()
    held_task = ws_endpoint(held)
    await asyncio.wait_for(held.accepted.wait(), timeout=5)
    assert _gauge() - gauge == 1

    rejected = _HeldSocket()
    await asyncio.wait_for(ws_endpoint(rejected), timeout=5)
    assert rejected.close_code == 4429
    assert not rejected.accepted.is_set()

    held.hang_up.set()
    await asyncio.wait_for(held_task, timeout=5)
    assert _gauge() == gauge
    key = connection_key(ORG, USER)
    assert set(shared_redis.keyspace.zsets.get(key, {})) == {remote.lease_id}

    # The freed slot is usable again from this instance.
    again = _HeldSocket()
    again_task = ws_endpoint(again)
    await asyncio.wait_for(again.accepted.wait(), timeout=5)
    again.hang_up.set()
    await asyncio.wait_for(again_task, timeout=5)


async def test_endpoint_heartbeat_refreshes_the_lease(
    monkeypatch: pytest.MonkeyPatch,
    ws_endpoint: Callable[[_HeldSocket], asyncio.Task[None]],
    shared_redis: FakeRedis,
    clock: FakeClock,
) -> None:
    monkeypatch.setattr(settings, "ws_chat_heartbeat_interval_seconds", 0.01)
    held = _HeldSocket()
    task = ws_endpoint(held)
    await asyncio.wait_for(held.accepted.wait(), timeout=5)
    key = connection_key(ORG, USER)
    clock.advance(40_000)

    async def refreshed() -> None:
        while True:
            scores = list(shared_redis.keyspace.zsets.get(key, {}).values())
            if scores and scores[0] == clock.now_ms + LEASE_MS:
                return
            await asyncio.sleep(0.005)

    await asyncio.wait_for(refreshed(), timeout=5)
    assert any(event["event"] == "heartbeat.ping" for event in held.sent)
    held.hang_up.set()
    await asyncio.wait_for(task, timeout=5)
    assert shared_redis.keyspace.zcard(key) == 0


async def test_endpoint_releases_the_slot_when_accept_fails(
    ws_endpoint: Callable[[_HeldSocket], asyncio.Task[None]], shared_redis: FakeRedis
) -> None:
    broken = _HeldSocket(accept_error=RuntimeError("handshake failed"))
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(ws_endpoint(broken), timeout=5)
    assert shared_redis.keyspace.zcard(connection_key(ORG, USER)) == 0


# -- live Redis (CI lane) -------------------------------------------------------------------


@pytest_asyncio.fixture
async def live_redis() -> AsyncIterator[Any]:
    from redis.asyncio import Redis

    url = os.environ.get("TEST_REDIS_URL", "").strip()
    if not url:
        pytest.skip("TEST_REDIS_URL is not set; skipping live Redis script tests")
    client: Any = Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Redis not reachable at TEST_REDIS_URL; skipping live script tests")
    try:
        yield client
    finally:
        await client.aclose()


@pytest.mark.requires_redis
async def test_live_acquire_refresh_and_expiry(live_redis: Any) -> None:
    key = f"rudix:test:chat:ws:conn:v1:{uuid4()}:{uuid4()}"
    try:
        assert await concurrency.try_acquire(
            live_redis, key=key, lease_id="a", limit=2, lease_ms=300
        )
        assert await concurrency.try_acquire(
            live_redis, key=key, lease_id="b", limit=2, lease_ms=300
        )
        assert not await concurrency.try_acquire(
            live_redis, key=key, lease_id="c", limit=2, lease_ms=300
        )
        assert await concurrency.try_refresh(live_redis, key=key, lease_id="a", lease_ms=60_000)
        assert not await concurrency.try_refresh(
            live_redis, key=key, lease_id="missing", lease_ms=60_000
        )
        await asyncio.sleep(0.4)
        # "b" expired (never refreshed): it cannot be refreshed and its slot is free again.
        assert not await concurrency.try_refresh(live_redis, key=key, lease_id="b", lease_ms=300)
        assert await concurrency.try_acquire(
            live_redis, key=key, lease_id="c", limit=2, lease_ms=60_000
        )
        assert await live_redis.zcard(key) == 2
        assert 0 < await live_redis.pttl(key) <= 60_000
    finally:
        await live_redis.delete(key)


@pytest.mark.requires_redis
async def test_live_refresh_matches_reference(live_redis: Any) -> None:
    seconds, micros = await live_redis.time()
    fake = FakeRedis(clock=FakeClock(int(seconds) * 1000 + int(micros) // 1000))
    key = f"rudix:test:chat:ws:conn:v1:{uuid4()}:{uuid4()}"
    try:
        for client in (live_redis, fake):
            assert await concurrency.try_acquire(
                client, key=key, lease_id="a", limit=1, lease_ms=60_000
            )
        for lease in ("a", "zzz"):
            live = await concurrency.try_refresh(
                live_redis, key=key, lease_id=lease, lease_ms=60_000
            )
            ref = await concurrency.try_refresh(fake, key=key, lease_id=lease, lease_ms=60_000)
            assert live == ref
    finally:
        await live_redis.delete(key)
