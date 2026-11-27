"""Run the production Lua scripts on a real Redis and compare with the reference impls.

Marked ``requires_redis``: skipped unless ``TEST_REDIS_URL`` points at a reachable Redis
(CI lane, or ``TEST_REDIS_URL=$REDIS_URL make test-postgres`` locally). It is opt-in, like
``TEST_DATABASE_URL``, so ``make test`` never writes into a developer's running Redis. The fakes elsewhere execute only the
Python reference implementations, so this is the check that the Lua matches them.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

os.environ.setdefault("ENVIRONMENT", "test")

from redis.asyncio import Redis

from app.auth import usage_touch
from app.auth.usage_touch import UsageTouch, UsageTouchKind
from app.rate_limit import sliding_window
from tests.redis_fakes import FakeClock, FakeRedis

pytestmark = pytest.mark.requires_redis


@pytest_asyncio.fixture
async def live_redis() -> AsyncIterator[Redis]:
    url = os.environ.get("TEST_REDIS_URL", "").strip()
    if not url:
        pytest.skip("TEST_REDIS_URL is not set; skipping live Redis script tests")
    client: Redis = Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Redis not reachable at TEST_REDIS_URL; skipping live script tests")
    try:
        yield client
    finally:
        await client.aclose()


async def _redis_now_ms(client: Redis) -> int:
    seconds, micros = await client.time()
    return int(seconds) * 1000 + int(micros) // 1000


async def test_sliding_window_script_matches_reference(live_redis: Redis) -> None:
    tag = uuid4().hex
    window_seconds = 2
    window_ms = window_seconds * 1000
    now = await _redis_now_ms(live_redis)
    clock = FakeClock(now)
    fake = FakeRedis(clock=clock)
    user_key = f"rate_limit:v2:{{live:{tag}}}:user"
    org_key = f"rate_limit:v2:{{live:{tag}}}:org"
    original_now = sliding_window.now_ms
    sliding_window.now_ms = clock
    try:
        for step in range(8):
            clock.now_ms = await _redis_now_ms(live_redis)
            live = await sliding_window.check(
                live_redis,
                user_key=user_key,
                user_limit=3,
                window_seconds=window_seconds,
                org_key=org_key,
                org_limit=5,
            )
            ref = await sliding_window.check(
                fake,
                user_key=user_key,
                user_limit=3,
                window_seconds=window_seconds,
                org_key=org_key,
                org_limit=5,
            )
            assert (live.allowed, live.scope, live.remaining) == (
                ref.allowed,
                ref.scope,
                ref.remaining,
            ), step
            # Both clocks were read within a few ms; retry estimates agree within that.
            assert abs(live.retry_after_ms - ref.retry_after_ms) <= 50, step
        pttl = await live_redis.pttl(f"{user_key}:w:{now // window_ms}")
        assert 0 < pttl <= 2 * window_ms
    finally:
        sliding_window.now_ms = original_now
        keys = [key async for key in live_redis.scan_iter(match=f"rate_limit:v2:{{live:{tag}}}*")]
        if keys:
            await live_redis.delete(*keys)


async def test_usage_touch_scripts_match_reference(
    live_redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Isolate the keyspace per run by pinning a unique environment-like hash tag.
    tag = uuid4().hex
    monkeypatch.setattr(usage_touch, "key_prefix", lambda: f"rudix:{{live-{tag}}}:usage_touch:")
    t1 = datetime(2026, 11, 1, 12, tzinfo=UTC)
    credential = uuid4()
    sequence = [
        UsageTouch(UsageTouchKind.api_key, credential, t1 + timedelta(seconds=5), "10.0.0.5"),
        UsageTouch(UsageTouchKind.api_key, credential, t1, "10.0.0.1"),
        UsageTouch(UsageTouchKind.service_account, uuid4(), t1),
    ]
    fake = FakeRedis()
    results: list[list[Any]] = []
    try:
        for client in (live_redis, fake):
            for touch in sequence:
                await usage_touch.buffer_touches(client, [touch])
            popped = await usage_touch.pop_touches(client, batch_size=10)
            again = await usage_touch.pop_touches(client, batch_size=10)
            results.append([sorted(popped, key=lambda t: t.member), again])
        assert results[0] == results[1]
        assert results[0][1] == []
    finally:
        keys = [key async for key in live_redis.scan_iter(match=f"rudix:{{live-{tag}}}*")]
        if keys:
            await live_redis.delete(*keys)
