"""R05-13 on PostgreSQL: a dropped WebSocket run resumes on another connection, holds no
database connection while it waits in its grace window, and its stored answer is rebuilt
through a tenant-bound session, in the default and strict RLS modes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from chat_golden_providers import install_providers
from chat_resume_support import (
    DroppableSocket,
    connect,
    install_ws,
    stranger,
    stream_sequences,
    wait_for_watchers,
)
from chat_stream_support import TEXT_A, RecordingSocket, StreamingRecordingProvider
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from test_chat_pipeline_concurrency_pg import _cleanup, _seed

from app.application.chat.transports.ws import WsSequence
from app.application.chat.transports.ws_resume import run_ws_resume
from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.config import RlsEnforcement, settings
from app.interfaces.http import chat as chat_api
from tests.redis_fakes import FakeClock, FakeRedis

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def small_pool_engine(pg_migrated_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(pg_migrated_url, pool_size=2, max_overflow=0, pool_timeout=2)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.parametrize("mode", [None, RlsEnforcement.strict], ids=["default", "strict"])
async def test_dropped_run_resumes_and_the_stored_answer_is_rebuilt(
    small_pool_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    mode: RlsEnforcement | None,
) -> None:
    factory = async_sessionmaker(
        bind=small_pool_engine, class_=AsyncSession, expire_on_commit=False
    )
    hold = asyncio.Event()
    provider = StreamingRecordingProvider(chunk_size=6, hold=hold, hold_at=3)
    world = await _seed(factory, provider)  # type: ignore[arg-type]
    install_providers(monkeypatch, provider)
    fake_redis = FakeRedis(clock=FakeClock(1_000_000_000))
    monkeypatch.setattr(redis_module, "redis_client", fake_redis)
    monkeypatch.setattr(settings, "chat_ws_resume_grace_seconds", 30)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    monkeypatch.setattr(settings, "feature_enable_embeddings", True)
    monkeypatch.setattr(settings, "rls_enforcement", mode)
    monkeypatch.setattr(chat_api, "SessionLocal", factory)
    principal = AuthenticatedPrincipal(
        user_id=str(world.user.id),
        organization_id=str(world.organization.id),
        email=world.user.email,
        roles=["member"],
        auth_provider="app",
    )
    install_ws(monkeypatch, [principal, principal])
    try:
        first = DroppableSocket()
        connection = connect(first)
        first.push("chat.start", {"chat_session_id": None, **world.payload})
        await first.wait_for("generation.delta")
        first.drop()
        await asyncio.wait_for(connection, timeout=10)
        seen = first.run_events()
        message_id = next(e["message_id"] for e in seen if e["message_id"])
        # The run waits in its grace window, mid-stream, without a database connection.
        assert provider.active_streams == 1
        assert small_pool_engine.pool.checkedout() == 0  # type: ignore[attr-defined]

        second = DroppableSocket()
        resumed = connect(second)
        second.push(
            "chat.resume",
            {"message_id": message_id, "last_stream_sequence": max(stream_sequences(seen))},
        )
        await second.wait_for("chat.resumed")
        hold.set()
        await second.wait_for("chat.completed", timeout=10)
        second.drop()
        await asyncio.wait_for(resumed, timeout=10)
        await wait_for_watchers()
        combined = stream_sequences(seen) + stream_sequences(second.run_events())
        assert combined == list(range(1, len(combined) + 1))
        assert first.deltas() + second.deltas() == TEXT_A

        fake_redis.clock.advance(settings.chat_resume_buffer_ttl_seconds * 1000 + 1)  # type: ignore[attr-defined]
        for who, expected in (
            (principal, "chat.completed"),
            (stranger(principal, same_org=True), "chat.error"),
        ):
            socket = RecordingSocket()
            await run_ws_resume(
                websocket=socket,
                payload={"message_id": message_id, "last_stream_sequence": 0},
                principal=who,
                sequence=WsSequence(),
                session_factory=factory,
            )
            assert socket.events[-1]["event"] == expected
        assert socket.events[-1]["safe_error_code"] == "resume_unavailable"
        assert small_pool_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    finally:
        await _cleanup(factory, world)
