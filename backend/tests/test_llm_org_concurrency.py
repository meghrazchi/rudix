"""Per-organisation LLM concurrency (Redis semaphore, R05-06).

Runs the acquire script through its Python reference implementation (``FakeRedis``), a
Redis that is down mid-request (``BrokenRedis``), and, under ``requires_redis``, the Lua
script against a real server.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from chat_stream_support import (
    RecordingSocket,
    StreamingRecordingProvider,
    counter_value,
    make_world,
    run_ws,
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import chat_query_client  # noqa: F401  (pytest fixture re-export)

from app.auth.token_codec import create_app_access_token
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.metrics import (
    LLM_ORG_CONCURRENCY_REJECTED_TOTAL,
    LLM_ORG_SEMAPHORE_UNAVAILABLE_TOTAL,
)
from app.db.tenant_context import tenant_context_scope
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.domains.ai.providers.resilience import ResilientChatProvider, breaker_registry
from app.domains.chat.services.llm_service import LLMService, ProviderBusyLLMServiceError
from app.rate_limit import concurrency
from app.rate_limit.concurrency import ProviderBusyError, org_call_slot, semaphore_key
from tests.redis_fakes import BrokenRedis, FakeClock, FakeRedis

pytestmark = pytest.mark.asyncio

ORG_A = uuid4()
ORG_B = uuid4()


def _plain(name: str) -> float:
    counter = {
        "rejected": LLM_ORG_CONCURRENCY_REJECTED_TOTAL,
        "unavailable": LLM_ORG_SEMAPHORE_UNAVAILABLE_TOTAL,
    }[name]
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total"):
                return float(sample.value)
    return 0.0


@pytest.fixture
def limit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_org_max_concurrent_calls", 1)
    monkeypatch.setattr(settings, "llm_org_semaphore_wait_ms", 0)
    monkeypatch.setattr(settings, "llm_org_semaphore_lease_seconds", 120)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis(clock=FakeClock(1_000_000))
    monkeypatch.setattr(redis_module, "redis_client", fake)
    return fake


@pytest.mark.usefixtures("limit_one")
async def test_second_call_of_one_organisation_is_busy_but_another_is_not(
    fake_redis: FakeRedis,
) -> None:
    rejected = _plain("rejected")
    with tenant_context_scope(ORG_A):
        async with org_call_slot("openai"):
            with pytest.raises(ProviderBusyError):
                async with org_call_slot("openai"):
                    pass
            with tenant_context_scope(ORG_B):
                async with org_call_slot("openai"):  # another organisation is not blocked
                    assert fake_redis.keyspace.zcard(semaphore_key(ORG_B)) == 1
        assert fake_redis.keyspace.zcard(semaphore_key(ORG_A)) == 0  # released by id
        async with org_call_slot("openai"):
            pass
    assert _plain("rejected") == rejected + 1
    assert semaphore_key(ORG_A).endswith(f"{{org:{ORG_A}}}")


@pytest.mark.usefixtures("limit_one")
async def test_expired_leases_are_purged(fake_redis: FakeRedis) -> None:
    key = semaphore_key(ORG_A)
    fake_redis.keyspace.zadd(key, {"crashed-worker": float(fake_redis.clock() + 1_000)})
    with tenant_context_scope(ORG_A):
        with pytest.raises(ProviderBusyError):
            async with org_call_slot("openai"):
                pass
        fake_redis.clock.advance(1_001)  # type: ignore[attr-defined]
        async with org_call_slot("openai"):
            assert fake_redis.keyspace.zcard(key) == 1


async def test_waiting_call_gets_the_slot_once_it_is_released(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    monkeypatch.setattr(settings, "llm_org_max_concurrent_calls", 1)
    monkeypatch.setattr(settings, "llm_org_semaphore_wait_ms", 2000)
    release = asyncio.Event()
    entered = asyncio.Event()

    async def holder() -> None:
        with tenant_context_scope(ORG_A):
            async with org_call_slot("openai"):
                entered.set()
                await release.wait()

    task = asyncio.create_task(holder())
    await entered.wait()
    with tenant_context_scope(ORG_A):
        asyncio.get_running_loop().call_later(0.1, release.set)
        async with org_call_slot("openai"):
            pass
    await task


async def test_no_limit_without_an_organisation_or_when_disabled(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    monkeypatch.setattr(settings, "llm_org_max_concurrent_calls", 1)
    async with org_call_slot("openai"):  # no tenant in context
        async with org_call_slot("openai"):
            pass
    monkeypatch.setattr(settings, "llm_org_max_concurrent_calls", 0)
    with tenant_context_scope(ORG_A):
        async with org_call_slot("openai"):
            async with org_call_slot("openai"):
                pass
    assert fake_redis.round_trips == 0


@pytest.mark.usefixtures("limit_one")
@pytest.mark.parametrize("redis", [None, BrokenRedis()], ids=["missing", "failing"])
async def test_missing_or_failing_redis_allows_and_counts(
    monkeypatch: pytest.MonkeyPatch, redis: Any
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", redis)
    before = _plain("unavailable")
    with tenant_context_scope(ORG_A):
        async with org_call_slot("openai"):
            async with org_call_slot("openai"):
                pass
    assert _plain("unavailable") == before + 2


@pytest.mark.usefixtures("limit_one")
async def test_release_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    async def broken_zrem(*_args: Any) -> int:
        raise ConnectionError("redis went away")

    monkeypatch.setattr(fake_redis, "zrem", broken_zrem)
    with tenant_context_scope(ORG_A):
        async with org_call_slot("openai"):
            pass


class _Answering:
    _model_name = "m"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls += 1
        return ChatCompletionResponse(
            content='{"answer":"ok","not_found":false,"citations":[]}',
            model="m",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1,
        )


@pytest.mark.usefixtures("limit_one")
async def test_busy_is_not_a_breaker_failure_and_llm_service_does_not_retry(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    provider = _Answering()
    service = LLMService(provider=provider)  # type: ignore[arg-type]
    with tenant_context_scope(ORG_A):
        async with org_call_slot("openai"):
            with pytest.raises(ProviderBusyError):
                await ResilientChatProvider(provider, "openai").complete(
                    ChatCompletionRequest(prompt="q", model="m")
                )
            with pytest.raises(ProviderBusyLLMServiceError):
                await service.generate_answer(prompt="q")
            with pytest.raises(ProviderBusyLLMServiceError):
                await service.stream_answer(prompt="q", on_text=_ignore)
    assert provider.calls == 0
    assert len(breaker_registry.get("openai", "m").failures) == 0
    assert (
        len(breaker_registry.get(settings.llm_default_provider, service.model_name).failures) == 0
    )


async def _ignore(_text: str) -> None:
    return None


# -- transports -----------------------------------------------------------------------------


def _fill(fake: FakeRedis, organization_id: Any) -> None:
    """Hold every slot of the organisation with a long lease."""
    fake.keyspace.zadd(semaphore_key(organization_id), {"busy": float(fake.clock() + 600_000)})


@pytest.mark.usefixtures("limit_one")
async def test_websocket_answers_provider_busy(
    chat_query_client: Any,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: FakeRedis,
) -> None:
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    _fill(fake_redis, world.organization.id)
    socket = RecordingSocket(provider)
    rejected = counter_value(LLM_ORG_CONCURRENCY_REJECTED_TOTAL)

    await run_ws(world, socket)

    errors = socket.of("chat.error")
    assert [e["safe_error_code"] for e in errors] == ["provider_busy"]
    assert "chat.completed" not in socket.names()
    assert provider.stream_calls == 0
    assert counter_value(LLM_ORG_CONCURRENCY_REJECTED_TOTAL) == rejected + 1


@pytest.mark.usefixtures("limit_one")
async def test_http_answers_429_provider_busy(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: FakeRedis,
) -> None:
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    _fill(fake_redis, world.organization.id)
    token = create_app_access_token(
        subject=world.user.external_auth_id,
        organization_id=str(world.organization.id),
        expires_in_seconds=600,
    )
    response = await chat_query_client.post(
        "/api/v1/chat",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-ID": str(world.organization.id),
        },
        json=world.payload,
    )
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "provider_busy"
    assert response.json()["error"]["code"] == "provider_busy"
    _fill(fake_redis, uuid4())  # another organisation's slots do not matter


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
async def test_acquire_script_matches_reference(live_redis: Any) -> None:
    seconds, micros = await live_redis.time()
    fake = FakeRedis(clock=FakeClock(int(seconds) * 1000 + int(micros) // 1000))
    key = f"rudix:test:llm:concurrency:v1:{{org:{uuid4()}}}"
    try:
        for lease in ("a", "b", "c"):
            live = await concurrency.try_acquire(
                live_redis, key=key, lease_id=lease, limit=2, lease_ms=60_000
            )
            ref = await concurrency.try_acquire(
                fake, key=key, lease_id=lease, limit=2, lease_ms=60_000
            )
            assert live == ref
        assert await live_redis.zcard(key) == fake.keyspace.zcard(key) == 2
        await live_redis.zrem(key, "a")
        await fake.zrem(key, "a")
        assert await concurrency.try_acquire(
            live_redis, key=key, lease_id="d", limit=2, lease_ms=60_000
        )
        assert await concurrency.try_acquire(fake, key=key, lease_id="d", limit=2, lease_ms=60_000)
        assert 0 < await live_redis.pttl(key) <= 60_000
    finally:
        await live_redis.delete(key)
