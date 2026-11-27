"""R05-03 on PostgreSQL: ``POST /chat/query/stream`` holds no database connection while the
model streams, in the default and strict RLS modes.

The request goes through the whole ASGI app (authentication and role dependencies included)
on an engine with ``pool_size=2``. The request-scoped session served authentication only;
it must not keep its connection checked out for the lifetime of the event stream.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from chat_golden_providers import install_providers
from chat_stream_support import StreamingRecordingProvider
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from test_chat_pipeline_concurrency_pg import _cleanup, _seed

from app.application.chat.transports import sse
from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, RlsEnforcement, settings
from app.db.session import get_db_session
from app.interfaces.http import chat as chat_api
from app.main import app
from app.models.usage import UsageEvent

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]

STREAM_PATH = "/api/v1/chat/query/stream"


@pytest_asyncio.fixture
async def small_pool_engine(pg_migrated_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(pg_migrated_url, pool_size=2, max_overflow=0, pool_timeout=2)
    try:
        yield engine
    finally:
        await engine.dispose()


class _Peer:
    """Raw ASGI client: sends the body, then ``http.disconnect`` when told to."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self._sent_body = False
        self.disconnect = asyncio.Event()
        self.saw_delta = asyncio.Event()
        self.messages: list[dict[str, Any]] = []

    async def receive(self) -> dict[str, Any]:
        if not self._sent_body:
            self._sent_body = True
            return {"type": "http.request", "body": self._body, "more_body": False}
        await self.disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if b"event: generation.delta" in message.get("body", b""):
            self.saw_delta.set()


async def _wait_for_runs() -> None:
    for _ in range(500):
        if not sse._active_runs:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("SSE pipeline task did not finish")


@pytest.mark.parametrize("mode", [None, RlsEnforcement.strict], ids=["default", "strict"])
async def test_sse_stream_holds_no_connection_while_the_model_streams(
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
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    monkeypatch.setattr(settings, "feature_enable_embeddings", True)
    monkeypatch.setattr(settings, "rls_enforcement", mode)
    monkeypatch.setattr(chat_api, "SessionLocal", factory)
    get_auth_provider.cache_clear()

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _request_session
    token = create_app_access_token(
        subject=world.user.external_auth_id,
        organization_id=str(world.organization.id),
        expires_in_seconds=600,
    )
    peer = _Peer(json.dumps(world.payload).encode())
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": STREAM_PATH,
        "raw_path": STREAM_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-organization-id", str(world.organization.id).encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 50001),
        "server": ("testserver", 80),
    }
    try:
        call = asyncio.create_task(app(scope, peer.receive, peer.send))
        await asyncio.wait_for(peer.saw_delta.wait(), timeout=10)
        assert peer.messages[0]["status"] == 200
        # The model is mid-stream: neither the request session nor the pipeline holds a
        # connection (R05-02, R05-03).
        assert small_pool_engine.pool.checkedout() == 0  # type: ignore[attr-defined]

        peer.disconnect.set()
        await asyncio.wait_for(call, timeout=10)
        await _wait_for_runs()

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
        assert [row.event_type for row in rows] == ["chat.completion.cancelled"]
        assert rows[0].metadata_json["transport"] == "sse"
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        get_auth_provider.cache_clear()
        await _cleanup(factory, world)
