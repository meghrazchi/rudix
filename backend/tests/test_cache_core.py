"""Application cache core (R04-05): versioned keys, single-flight, fallbacks, kill switch."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, TypeAdapter

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")

from app.clients import redis_client as redis_module
from app.core import cache
from app.core.cache import OrgScope, UserScope, get_or_load
from app.core.cache_invalidation import apply_invalidations
from app.core.config import settings
from tests.redis_fakes import BrokenRedis, FakeClock, FakeRedis

_NS = "test_ns"
_INT = TypeAdapter(int)
_P = f"rudix:{settings.environment.value}"


class _Payload(BaseModel):
    name: str
    roles: list[str]


def _counter(metric: Any, **labels: str) -> float:
    return float(metric.labels(**labels)._value.get())


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(1_800_000_000_000)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> Iterator[FakeRedis]:
    redis = FakeRedis(clock=clock)
    monkeypatch.setattr(redis_module, "redis_client", redis)
    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "now_ms", clock)
    yield redis


class _Loader:
    def __init__(self, value: Any, *, delay: float = 0.0) -> None:
        self.value = value
        self.calls = 0
        self.delay = delay

    async def __call__(self) -> Any:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.value


async def _get(scope: cache.CacheScope, loader: Any, *, key_id: str = "k", ttl: int = 30) -> Any:
    return await get_or_load(
        scope=scope, namespace=_NS, key_id=key_id, ttl=ttl, adapter=_INT, loader=loader
    )


@pytest.mark.asyncio
async def test_miss_then_hit_and_value_key_layout(fake_redis: FakeRedis) -> None:
    org_id = uuid4()
    loader = _Loader(7)
    hits = _counter(cache.CACHE_HITS_TOTAL, namespace=_NS)
    misses = _counter(cache.CACHE_MISSES_TOTAL, namespace=_NS)

    assert await _get(OrgScope(org_id), loader) == 7
    assert await _get(OrgScope(org_id), loader) == 7

    assert loader.calls == 1
    assert _counter(cache.CACHE_HITS_TOTAL, namespace=_NS) == hits + 1
    assert _counter(cache.CACHE_MISSES_TOTAL, namespace=_NS) == misses + 1
    version = fake_redis.keyspace.get(f"{_P}:org:{org_id}:version")
    assert version == "1800000000000"
    value_key = f"{_P}:org:{org_id}:v{version}:{_NS}:k"
    assert fake_redis.keyspace.get(value_key) == "7"
    assert fake_redis.keyspace.pttl(value_key) == 30_000


@pytest.mark.asyncio
async def test_pydantic_models_round_trip(fake_redis: FakeRedis) -> None:
    adapter = TypeAdapter(_Payload)
    loader = _Loader(_Payload(name="a", roles=["x", "y"]))
    scope = UserScope(uuid4())
    for _ in range(2):
        value = await get_or_load(
            scope=scope, namespace=_NS, key_id="p", ttl=5, adapter=adapter, loader=loader
        )
        assert value == _Payload(name="a", roles=["x", "y"])
    assert loader.calls == 1


@pytest.mark.asyncio
async def test_scopes_and_orgs_never_share_keys(fake_redis: FakeRedis) -> None:
    org_a, org_b = uuid4(), uuid4()
    assert await _get(OrgScope(org_a), _Loader(1)) == 1
    assert await _get(OrgScope(org_b), _Loader(2)) == 2
    assert await _get(UserScope(org_a), _Loader(3)) == 3
    assert await _get(OrgScope(org_a), _Loader(99)) == 1
    assert await _get(OrgScope(org_b), _Loader(99)) == 2


@pytest.mark.asyncio
async def test_version_bump_orphans_old_keys(fake_redis: FakeRedis, clock: FakeClock) -> None:
    org_id, user_id = uuid4(), uuid4()
    assert await _get(OrgScope(org_id), _Loader(1)) == 1
    assert await _get(UserScope(user_id), _Loader(10)) == 10
    old_key = f"{_P}:org:{org_id}:v{clock.now_ms}:{_NS}:k"

    await apply_invalidations({"org": {str(org_id)}, "user": set()})

    reloaded = _Loader(2)
    assert await _get(OrgScope(org_id), reloaded) == 2
    assert reloaded.calls == 1
    # The old value is orphaned (left to expire), not deleted.
    assert fake_redis.keyspace.get(old_key) == "1"
    assert fake_redis.keyspace.get(f"{_P}:org:{org_id}:version") == str(clock.now_ms + 1)
    # The user scope was not bumped.
    assert await _get(UserScope(user_id), _Loader(99)) == 10


@pytest.mark.asyncio
async def test_missing_version_initialised_from_clock_after_eviction(
    fake_redis: FakeRedis, clock: FakeClock
) -> None:
    org_id = uuid4()
    version_key = f"{_P}:org:{org_id}:version"
    assert await _get(OrgScope(org_id), _Loader(1)) == 1
    first_version = int(fake_redis.keyspace.get(version_key) or 0)

    fake_redis.keyspace.delete(version_key)  # eviction
    clock.advance(5)
    assert await _get(OrgScope(org_id), _Loader(2)) == 2
    second_version = int(fake_redis.keyspace.get(version_key) or 0)
    assert second_version == first_version + 5

    # A bump on an evicted key restarts from the clock too, never from 1.
    fake_redis.keyspace.delete(version_key)
    clock.advance(5)
    await apply_invalidations({"org": {str(org_id)}})
    assert int(fake_redis.keyspace.get(version_key) or 0) == clock.now_ms + 1


@pytest.mark.asyncio
async def test_version_set_nx_race_reads_winner(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another process initialises the version between our GET and SET NX."""
    org_id = uuid4()
    version_key = f"{_P}:org:{org_id}:version"
    original_set = fake_redis.set

    async def racing_set(key: str, value: Any, ex: int | None = None, nx: bool = False) -> Any:
        if key == version_key and nx:
            fake_redis.keyspace.set(version_key, "42")
        return await original_set(key, value, ex=ex, nx=nx)

    monkeypatch.setattr(fake_redis, "set", racing_set)
    assert await _get(OrgScope(org_id), _Loader(1)) == 1
    assert fake_redis.keyspace.get(f"{_P}:org:{org_id}:v42:{_NS}:k") == "1"


@pytest.mark.asyncio
async def test_single_flight_runs_loader_once(fake_redis: FakeRedis) -> None:
    loader = _Loader(5, delay=0.02)
    scope = OrgScope(uuid4())
    results = await asyncio.gather(*(_get(scope, loader) for _ in range(20)))
    assert results == [5] * 20
    assert loader.calls == 1
    assert cache._inflight == {}


@pytest.mark.asyncio
async def test_single_flight_followers_fall_back_when_leader_fails(
    fake_redis: FakeRedis,
) -> None:
    scope = OrgScope(uuid4())
    calls = 0

    async def flaky() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        if calls == 1:
            raise RuntimeError("leader failed")
        return 9

    results = await asyncio.gather(*(_get(scope, flaky) for _ in range(5)), return_exceptions=True)
    assert sum(isinstance(r, RuntimeError) for r in results) == 1
    assert [r for r in results if not isinstance(r, BaseException)] == [9, 9, 9, 9]
    assert cache._inflight == {}


@pytest.mark.asyncio
async def test_loader_exception_is_not_cached(fake_redis: FakeRedis) -> None:
    scope = UserScope(uuid4())

    async def failing() -> int:
        raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        await _get(scope, failing)
    loader = _Loader(3)
    assert await _get(scope, loader) == 3
    assert loader.calls == 1


@pytest.mark.asyncio
async def test_broken_redis_falls_back_to_loader_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    monkeypatch.setattr(settings, "cache_enabled", True)
    before = _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="version")
    loader = _Loader(4)
    assert await _get(OrgScope(uuid4()), loader) == 4
    assert await _get(OrgScope(uuid4()), loader) == 4
    assert loader.calls == 2
    assert _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="version") == before + 2


@pytest.mark.asyncio
async def test_missing_client_falls_back_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    monkeypatch.setattr(settings, "cache_enabled", True)
    before = _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="unavailable")
    assert await _get(OrgScope(uuid4()), _Loader(1)) == 1
    assert _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="unavailable") == before + 1


@pytest.mark.asyncio
async def test_kill_switch_skips_redis(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "cache_enabled", False)
    before = _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="disabled")
    loader = _Loader(1)
    scope = OrgScope(uuid4())
    assert await _get(scope, loader) == 1
    assert await _get(scope, loader) == 1
    assert loader.calls == 2
    assert fake_redis.round_trips == 0
    assert _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="disabled") == before + 2


class _SlowRedis(FakeRedis):
    def __init__(self, *, slow: set[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.slow = slow

    async def get(self, key: str) -> str | None:
        if "GET" in self.slow:
            await asyncio.sleep(1)
        return await super().get(key)

    async def set(
        self, key: str, value: Any, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if "SET_VALUE" in self.slow and not nx:
            await asyncio.sleep(1)
        return await super().set(key, value, ex=ex, nx=nx)


@pytest.mark.asyncio
async def test_slow_version_read_times_out_to_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "redis_client", _SlowRedis(slow={"GET"}))
    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr(settings, "cache_operation_timeout_ms", 20)
    before = _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="version")
    loader = _Loader(6)
    assert await asyncio.wait_for(_get(OrgScope(uuid4()), loader), timeout=0.5) == 6
    assert loader.calls == 1
    assert _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="version") == before + 1


@pytest.mark.asyncio
async def test_slow_value_write_times_out_but_returns_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", _SlowRedis(slow={"SET_VALUE"}))
    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr(settings, "cache_operation_timeout_ms", 20)
    before = _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="set")
    assert await asyncio.wait_for(_get(OrgScope(uuid4()), _Loader(8)), timeout=0.5) == 8
    assert _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="set") == before + 1


@pytest.mark.asyncio
async def test_value_read_error_falls_back(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = OrgScope(uuid4())
    assert await _get(scope, _Loader(1)) == 1  # initialises the version key
    original_get = fake_redis.get

    async def failing_value_get(key: str) -> str | None:
        if key.endswith(f":{_NS}:k"):
            raise ConnectionError("reset")
        return await original_get(key)

    monkeypatch.setattr(fake_redis, "get", failing_value_get)
    before = _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="get")
    loader = _Loader(2)
    assert await _get(scope, loader) == 2
    assert loader.calls == 1
    assert _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="get") == before + 1


@pytest.mark.asyncio
async def test_undecodable_value_is_reloaded(fake_redis: FakeRedis, clock: FakeClock) -> None:
    org_id = uuid4()
    assert await _get(OrgScope(org_id), _Loader(1)) == 1
    fake_redis.keyspace.set(f"{_P}:org:{org_id}:v{clock.now_ms}:{_NS}:k", "not-json")
    before = _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="decode")
    loader = _Loader(2)
    assert await _get(OrgScope(org_id), loader) == 2
    assert loader.calls == 1
    assert _counter(cache.CACHE_ERRORS_TOTAL, namespace=_NS, operation="decode") == before + 1


@pytest.mark.asyncio
async def test_invalidation_counts_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    unavailable = _counter(cache.CACHE_INVALIDATIONS_TOTAL, scope="user", result="unavailable")
    await apply_invalidations({"user": {"u1", "u2"}})
    assert (
        _counter(cache.CACHE_INVALIDATIONS_TOTAL, scope="user", result="unavailable")
        == unavailable + 2
    )

    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    errors = _counter(cache.CACHE_INVALIDATIONS_TOTAL, scope="org", result="error")
    await apply_invalidations({"org": {"o1"}})
    assert _counter(cache.CACHE_INVALIDATIONS_TOTAL, scope="org", result="error") == errors + 1

    await apply_invalidations({"org": set()})  # nothing to do
