"""R05-03 on PostgreSQL: a cancelled stream records partial usage in its own short write
session and leaves no connection checked out, in the default and strict RLS modes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from chat_golden_providers import install_providers
from chat_stream_support import RecordingSocket, StreamingRecordingProvider
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from test_chat_pipeline_concurrency_pg import _cleanup, _seed

from app.core.config import RlsEnforcement, settings
from app.interfaces.http import chat as chat_api
from app.models.chat import ChatSession
from app.models.usage import UsageEvent

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def small_pool_engine(pg_migrated_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(pg_migrated_url, pool_size=2, max_overflow=0, pool_timeout=2)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.parametrize("mode", [None, RlsEnforcement.strict], ids=["default", "strict"])
async def test_cancelled_stream_writes_partial_usage_and_releases_connections(
    small_pool_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    mode: RlsEnforcement | None,
) -> None:
    factory = async_sessionmaker(
        bind=small_pool_engine, class_=AsyncSession, expire_on_commit=False
    )
    hold = asyncio.Event()  # never set: the provider stalls mid-stream
    provider = StreamingRecordingProvider(chunk_size=6, hold=hold)
    world = await _seed(factory, provider)  # type: ignore[arg-type]
    install_providers(monkeypatch, provider)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    monkeypatch.setattr(settings, "feature_enable_embeddings", True)
    monkeypatch.setattr(settings, "rls_enforcement", mode)
    monkeypatch.setattr(chat_api, "SessionLocal", factory)
    socket = RecordingSocket(provider)
    principal = chat_api.AuthenticatedPrincipal(
        user_id=str(world.user.id),
        organization_id=str(world.organization.id),
        email=world.user.email,
        roles=["member"],
        auth_provider="app",
    )
    try:
        run = asyncio.create_task(
            chat_api._run_ws_chat_pipeline(
                websocket=socket,  # type: ignore[arg-type]
                payload={"chat_session_id": None, **world.payload},
                principal=principal,
                request_id="pg-cancel",
                sequence_start=0,
            )
        )
        await socket.wait_for("generation.delta")
        # While the model streams no connection is held (R05-02).
        assert small_pool_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run

        assert provider.closed_streams == 1 and provider.finished_streams == 0
        assert small_pool_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(UsageEvent).where(
                            UsageEvent.organization_id == world.organization.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            chat_sessions = await session.scalar(
                select(func.count())
                .select_from(ChatSession)
                .where(ChatSession.organization_id == world.organization.id)
            )
        assert [row.event_type for row in rows] == ["chat.completion.cancelled"]
        assert rows[0].metadata_json["usage_estimated"] is True
        assert chat_sessions == 0
    finally:
        await _cleanup(factory, world)
