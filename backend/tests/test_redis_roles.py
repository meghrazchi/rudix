"""Redis roles (R08-05, contract 5.2.7).

State keys (rate limits, semaphores, tickets, resume buffer, realtime, usage touch, cache
version keys) always use ``redis_client`` (``REDIS_URL``). Cached values use
``cache_redis_client`` (``REDIS_CACHE_URL``) when set, else ``redis_client``. Celery results
use ``CELERY_RESULT_BACKEND_URL`` when set, else ``REDIS_URL``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from app.application.chat.ws_connection_limit import WsConnectionLimiter
from app.auth import usage_touch
from app.auth.models import AuthenticatedPrincipal
from app.clients import factory
from app.clients import redis_client as redis_module
from app.clients.rabbitmq_client import redis_result_backend_url
from app.core import cache
from app.core.cache import OrgScope, get_or_load
from app.core.cache_invalidation import apply_invalidations
from app.core.config import settings
from app.rate_limit.counter import RateLimitDecision, RateLimitScope, consume_rate_limit
from tests.redis_fakes import BrokenRedis, FakeClock, FakeRedis, align_app_clock

_INT = TypeAdapter(int)
APP_DIR = Path(__file__).resolve().parent.parent / "app"


class _PingableRedis(FakeRedis):
    def __init__(self, *, clock: Any = None, ping_ok: bool = True) -> None:
        super().__init__(clock=clock)
        self.ping_ok = ping_ok
        self.closed = False

    async def ping(self) -> bool:
        if not self.ping_ok:
            raise ConnectionError("down")
        return True

    async def aclose(self) -> None:
        self.closed = True


class _Loader:
    def __init__(self, value: int) -> None:
        self.value = value
        self.calls = 0

    async def __call__(self) -> int:
        self.calls += 1
        return self.value


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(1_800_000_000_000)


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> Iterator[FakeRedis]:
    redis = FakeRedis(clock=clock)
    monkeypatch.setattr(redis_module, "redis_client", redis)
    monkeypatch.setattr(settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "now_ms", clock)
    yield redis


@pytest.fixture
def cache_store(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> FakeRedis:
    redis = FakeRedis(clock=clock)
    monkeypatch.setattr(redis_module, "cache_redis_client", redis)
    return redis


async def _get(org: str, loader: _Loader) -> int:
    return await get_or_load(
        scope=OrgScope(org), namespace="roles_ns", key_id="k", ttl=60, adapter=_INT, loader=loader
    )


# -- cached values vs. version keys ----------------------------------------------------------


async def test_values_hit_and_miss_on_the_cache_client(
    state: FakeRedis, cache_store: FakeRedis
) -> None:
    org = str(uuid4())
    loader = _Loader(7)
    assert await _get(org, loader) == 7
    assert await _get(org, loader) == 7
    assert loader.calls == 1

    version_key = cache.version_key("org", org)
    assert set(state.keyspace.strings) == {version_key}
    assert version_key not in cache_store.keyspace.strings
    assert [k for k in cache_store.keyspace.strings if k.endswith(":roles_ns:k")]


async def test_version_bump_on_state_invalidates_values_on_the_cache_client(
    state: FakeRedis, cache_store: FakeRedis
) -> None:
    org = str(uuid4())
    loader = _Loader(1)
    await _get(org, loader)
    cache_round_trips = cache_store.round_trips

    await apply_invalidations({"org": {org}, "user": set()})
    assert cache_store.round_trips == cache_round_trips  # bumps never touch the cache Redis
    assert "INCR" in state.commands

    loader.value = 2
    assert await _get(org, loader) == 2
    assert loader.calls == 2


async def test_evicting_every_cached_value_never_resets_a_version(
    state: FakeRedis, cache_store: FakeRedis
) -> None:
    org = str(uuid4())
    await _get(org, _Loader(1))
    await apply_invalidations({"org": {org}, "user": set()})
    version_before = state.keyspace.get(cache.version_key("org", org))
    cache_store.keyspace.strings.clear()  # allkeys-lru evicted everything
    await _get(org, _Loader(1))
    assert state.keyspace.get(cache.version_key("org", org)) == version_before


async def test_cache_client_down_degrades_to_a_miss(
    monkeypatch: pytest.MonkeyPatch, state: FakeRedis
) -> None:
    monkeypatch.setattr(redis_module, "cache_redis_client", BrokenRedis())
    org = str(uuid4())
    errors = float(
        cache.CACHE_ERRORS_TOTAL.labels(namespace="roles_ns", operation="get")._value.get()
    )
    loader = _Loader(5)
    assert await _get(org, loader) == 5
    assert await _get(org, loader) == 5
    assert loader.calls == 2
    after = float(
        cache.CACHE_ERRORS_TOTAL.labels(namespace="roles_ns", operation="get")._value.get()
    )
    assert after - errors == 2


async def test_without_a_cache_url_values_share_the_state_client(
    monkeypatch: pytest.MonkeyPatch, state: FakeRedis
) -> None:
    monkeypatch.setattr(redis_module, "cache_redis_client", None)
    assert cache.value_redis_client() is state
    org = str(uuid4())
    loader = _Loader(3)
    await _get(org, loader)
    await _get(org, loader)
    assert loader.calls == 1
    assert [k for k in state.keyspace.strings if k.endswith(":roles_ns:k")]


async def test_missing_state_client_falls_back_to_the_loader(
    monkeypatch: pytest.MonkeyPatch, cache_store: FakeRedis
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    monkeypatch.setattr(settings, "cache_enabled", True)
    loader = _Loader(9)
    assert await _get(str(uuid4()), loader) == 9
    assert cache_store.round_trips == 0


# -- state keys stay on REDIS_URL ------------------------------------------------------------


async def test_state_keys_use_the_state_client(
    monkeypatch: pytest.MonkeyPatch, state: FakeRedis, cache_store: FakeRedis, clock: FakeClock
) -> None:
    align_app_clock(monkeypatch, clock)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_disable_in_test", False)
    monkeypatch.setattr(settings, "rate_limit_disable_in_development", False)
    principal = AuthenticatedPrincipal(
        user_id="u", organization_id="o", roles=["member"], auth_provider="test"
    )
    outcome = await consume_rate_limit(
        scope=RateLimitScope.chat, endpoint="/chat", principal=principal
    )
    assert outcome.decision == RateLimitDecision.allowed

    monkeypatch.setattr(settings, "ws_chat_connection_limit_backend", "redis")
    slot = await WsConnectionLimiter(counts={}).acquire(organization_id="o", user_id="u")
    assert slot is not None and slot.backend == "redis"

    touch = usage_touch.UsageTouch(
        kind=usage_touch.UsageTouchKind.api_key,
        credential_id=uuid4(),
        used_at=datetime.now(UTC),
        ip_address=None,
    )
    await usage_touch.record_touches([touch])

    assert state.script_calls  # rate limit, connection lease, usage touch
    assert len(state.script_calls) == 3
    assert cache_store.round_trips == 0


def test_only_the_cache_module_reads_the_cache_client() -> None:
    """Every state path keeps reading ``redis_client``; only the cache (values), the
    readiness probe, and the lifespan know the cache client."""
    allowed = {
        "clients/redis_client.py",
        "core/cache.py",
        "core/lifespan.py",
        "api/health.py",
    }
    pattern = re.compile(r"cache_redis_client|init_cache_redis|check_cache_redis_health")
    users = {
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if pattern.search(path.read_text())
    }
    assert users <= allowed
    assert "core/cache.py" in users


# -- clients and Celery results --------------------------------------------------------------


async def test_cache_client_is_created_only_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[str | None] = []
    client = _PingableRedis()

    def fake_factory(config: Any, *, url: str | None = None) -> Any:
        del config
        created.append(url)
        return client

    monkeypatch.setattr(redis_module, "create_redis_client", fake_factory)
    monkeypatch.setattr(redis_module, "cache_redis_client", None)
    monkeypatch.setattr(settings, "redis_cache_url", None)
    await redis_module.init_cache_redis()
    assert redis_module.cache_redis_client is None and created == []
    assert await redis_module.check_cache_redis_health() is False

    monkeypatch.setattr(settings, "redis_cache_url", "redis://cache.invalid:6379/1")
    await redis_module.init_cache_redis()
    assert redis_module.cache_redis_client is client
    assert created == ["redis://cache.invalid:6379/1"]
    assert await redis_module.check_cache_redis_health() is True

    client.ping_ok = False
    assert await redis_module.check_cache_redis_health() is False

    await redis_module.close_cache_redis()
    assert client.closed and redis_module.cache_redis_client is None
    await redis_module.close_cache_redis()  # idempotent


async def test_cache_client_init_failure_leaves_it_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    down = _PingableRedis(ping_ok=False)
    monkeypatch.setattr(redis_module, "create_redis_client", lambda config, *, url=None: down)
    monkeypatch.setattr(redis_module, "cache_redis_client", None)
    monkeypatch.setattr(settings, "redis_cache_url", "redis://cache.invalid:6379/1")
    with pytest.raises(ConnectionError):
        await redis_module.init_cache_redis()
    assert down.closed and redis_module.cache_redis_client is None
    # The readiness probe retries the connection and reports it down.
    assert await redis_module.check_cache_redis_health() is False


def test_factory_builds_a_client_for_another_url() -> None:
    client = factory.create_redis_client(settings, url="redis://cache.invalid:6390/3")
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["host"] == "cache.invalid" and kwargs["port"] == 6390 and kwargs["db"] == 3
    default = factory.create_redis_client(settings)
    assert default.connection_pool.connection_kwargs["host"] == settings.redis_url.host


def test_celery_results_use_their_own_url_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "celery_result_backend_enabled", True)
    monkeypatch.setattr(settings, "celery_result_backend_url", None)
    assert redis_result_backend_url() == str(settings.redis_url)
    monkeypatch.setattr(settings, "celery_result_backend_url", "redis://results.invalid:6379/2")
    assert redis_result_backend_url() == "redis://results.invalid:6379/2"
    monkeypatch.setattr(settings, "celery_result_backend_enabled", False)
    assert redis_result_backend_url() is None


def test_defaults_keep_one_redis() -> None:
    fields = type(settings).model_fields
    assert fields["redis_cache_url"].default is None
    assert fields["celery_result_backend_url"].default is None
    snapshot = settings.sanitized_snapshot()["infrastructure"]
    assert snapshot["redis_cache_url_set"] is (settings.redis_cache_url is not None)
    assert snapshot["celery_result_backend_url_set"] is (
        settings.celery_result_backend_url is not None
    )
