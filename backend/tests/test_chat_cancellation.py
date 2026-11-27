"""Cancellation of a streaming chat answer (R05-03).

``chat.cancel`` on the WebSocket cancels the pipeline task mid-stream: the provider stream
is closed, a ``chat.completion.cancelled`` usage row records what was spent, and no chat
message or questions-quota increment is written.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from chat_golden_support import _question_usage
from chat_stream_support import (
    StreamingRecordingProvider,
    counter_value,
    make_world,
    principal_for,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import chat_query_client  # noqa: F401  (pytest fixture re-export)

from app.application.chat import ws_auth
from app.application.chat.pipeline import partial_usage
from app.application.chat.pipeline.ledger import TokenLedger
from app.application.chat.pipeline.stream_state import StreamState
from app.core.config import settings
from app.core.metrics import CHAT_STREAM_CANCELLED_TOTAL
from app.interfaces.http import chat as chat_api
from app.models.chat import ChatMessage, ChatSession
from app.models.usage import UsageEvent

pytestmark = [pytest.mark.asyncio]


class _ScriptedSocket:
    """Drives ``chat_websocket``: commands are pushed by the test; events are recorded."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.client = None
        self.events: list[dict[str, Any]] = []
        self._incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self._sent = asyncio.Event()

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        return None

    async def send_text(self, text: str) -> None:
        self.events.append(json.loads(text))
        self._sent.set()

    async def receive_text(self) -> str:
        from fastapi import WebSocketDisconnect

        item = await self._incoming.get()
        if item is None:
            raise WebSocketDisconnect()
        return item

    def push(self, command: str, payload: dict[str, Any] | None = None) -> None:
        self._incoming.put_nowait(json.dumps({"command": command, "payload": payload}))

    def disconnect(self) -> None:
        self._incoming.put_nowait(None)

    def names(self) -> list[str]:
        return [e["event"] for e in self.events if e["event"] != "activity.step.update"]

    async def wait_for(self, name: str, timeout: float = 5.0) -> None:
        async def _wait() -> None:
            while name not in self.names():
                self._sent.clear()
                await self._sent.wait()

        await asyncio.wait_for(_wait(), timeout)


async def test_chat_cancel_mid_stream_closes_the_provider_and_records_partial_usage(
    chat_query_client: Any,  # noqa: F811  (settings and providers)
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hold = asyncio.Event()  # never set: the provider stalls mid-stream
    provider = StreamingRecordingProvider(chunk_size=6, hold=hold)
    world = await make_world(db_session, monkeypatch, provider)
    principal = principal_for(world)

    async def fake_auth(**_kwargs: Any) -> ws_auth.WsAuthResult:
        return ws_auth.WsAuthResult(principal=principal, method="ticket")

    monkeypatch.setattr(settings, "feature_chat_websocket_enabled", True)
    monkeypatch.setattr(chat_api, "authenticate_ws_handshake", fake_auth)
    cancelled_before = counter_value(CHAT_STREAM_CANCELLED_TOTAL, transport="ws")
    questions_before = await _question_usage(db_session, world.organization.id)
    socket = _ScriptedSocket()
    connection = asyncio.create_task(chat_api.chat_websocket(socket, ticket="t"))  # type: ignore[arg-type]

    socket.push("chat.start", {"chat_session_id": None, **world.payload})
    await socket.wait_for("generation.delta")
    assert provider.active_streams == 1
    socket.push("chat.cancel")
    await socket.wait_for("chat.cancelled")
    socket.disconnect()
    await asyncio.wait_for(connection, timeout=5)

    names = socket.names()
    assert "chat.completed" not in names and "generation.final" not in names
    assert provider.closed_streams == 1 and provider.finished_streams == 0
    assert counter_value(CHAT_STREAM_CANCELLED_TOTAL, transport="ws") == cancelled_before + 1

    usage = (await db_session.execute(select(UsageEvent))).scalars().all()
    assert [u.event_type for u in usage] == ["chat.completion.cancelled"]
    row = usage[0]
    meta = row.metadata_json
    assert meta["cancelled"] is True and meta["transport"] == "ws"
    assert meta["usage_estimated"] is True  # cut off before the usage chunk
    assert meta["chat_session_id"] is None  # the new conversation was never written
    assert meta["generation_attempts"] == 1 and meta["streamed_chars"] > 0
    assert set(meta["token_ledger"]) == {"retrieve", "generate"}
    assert meta["token_ledger"]["generate"]["estimated"] is True
    assert row.input_tokens > 7 and row.output_tokens > 0  # embedding + estimated prompt
    assert row.model_name == settings.openai_llm_model
    assert "question" not in json.dumps(meta).lower()

    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert await db_session.scalar(select(func.count()).select_from(ChatSession)) == 0
    assert await _question_usage(db_session, world.organization.id) == questions_before


class _Recorder:
    def __init__(self) -> None:
        self.calls = 0


def _fake_ctx(
    *,
    assistant_message: object | None = None,
    delay: float = 0.0,
    fail: bool = False,
) -> SimpleNamespace:
    rows: list[dict[str, Any]] = []
    recorder = _Recorder()

    class _Session:
        async def commit(self) -> None:
            return None

    class _Write:
        async def __aenter__(self) -> _Session:
            recorder.calls += 1
            if delay:
                await asyncio.sleep(delay)
            if fail:
                raise RuntimeError("database unavailable")
            return _Session()

        async def __aexit__(self, *args: object) -> bool:
            return False

    async def create_usage_event(_session: object, **kwargs: Any) -> None:
        rows.append(kwargs)

    sessions = SimpleNamespace(write=lambda: _Write())
    llm_service = SimpleNamespace(
        _estimate_cost=lambda prompt_tokens, completion_tokens: (
            Decimal(prompt_tokens + completion_tokens) / Decimal(1_000_000)
        )
    )
    return SimpleNamespace(
        request=SimpleNamespace(
            organization_id=uuid4(),
            user_id=uuid4(),
            request_id="req-1",
            transport="ws",
        ),
        ids=SimpleNamespace(chat_session_id=uuid4(), new_chat_session=False),
        persist=SimpleNamespace(assistant_message=assistant_message),
        ledger=TokenLedger(),
        stream=StreamState(mode="live"),
        sessions=sessions,
        deps=SimpleNamespace(
            usage_repository=SimpleNamespace(create_usage_event=create_usage_event),
            llm_service=llm_service,
        ),
        rows=rows,
        write_calls=recorder,
    )


async def test_cancel_after_persistence_writes_no_extra_row() -> None:
    ctx = _fake_ctx(assistant_message=object())
    ctx.ledger.record("retrieve", None, "embed", 7, 0)
    assert await partial_usage.record_cancelled_usage(ctx) is False  # type: ignore[arg-type]
    assert ctx.write_calls.calls == 0


async def test_reported_usage_is_used_when_the_provider_sent_it() -> None:
    ctx = _fake_ctx()
    ctx.ledger.record("retrieve", None, "embed", 7, 0)
    attempt = ctx.stream.progress.begin("openai", "gpt", 4000)
    attempt.prompt_tokens, attempt.completion_tokens = 900, 40
    ctx.stream.streamed.append("partial")

    assert await partial_usage.record_cancelled_usage(ctx) is True  # type: ignore[arg-type]

    (row,) = ctx.rows
    assert row["event_type"] == "chat.completion.cancelled"
    assert (row["input_tokens"], row["output_tokens"]) == (907, 40)
    assert row["model_name"] == "gpt" and row["provider_key"] == "openai"
    assert row["cost_usd"] == Decimal(940) / Decimal(1_000_000)
    meta = row["metadata"]
    assert meta["usage_estimated"] is False
    assert meta["chat_session_id"] == str(ctx.ids.chat_session_id)
    assert meta["streamed_chars"] == len("partial")


async def test_completed_generation_is_not_counted_twice() -> None:
    ctx = _fake_ctx()
    ctx.ledger.record("generate", "openai", "gpt", 31, 17)
    ctx.stream.progress.begin("openai", "gpt", 400)
    assert await partial_usage.record_cancelled_usage(ctx) is True  # type: ignore[arg-type]
    assert (ctx.rows[0]["input_tokens"], ctx.rows[0]["output_tokens"]) == (31, 17)


async def test_nothing_spent_writes_no_row() -> None:
    ctx = _fake_ctx()
    assert await partial_usage.record_cancelled_usage(ctx) is False  # type: ignore[arg-type]
    assert ctx.rows == [] and ctx.write_calls.calls == 0


async def test_slow_or_failing_write_is_logged_and_never_raises() -> None:
    slow = _fake_ctx(delay=0.5)
    slow.ledger.record("retrieve", None, "embed", 7, 0)
    written = await partial_usage.record_cancelled_usage(  # type: ignore[arg-type]
        slow, timeout_seconds=0.01
    )
    assert written is False

    failing = _fake_ctx(fail=True)
    failing.ledger.record("retrieve", None, "embed", 7, 0)
    assert await partial_usage.record_cancelled_usage(failing) is False  # type: ignore[arg-type]
    assert failing.rows == []


async def test_a_second_cancellation_lets_the_shielded_write_finish() -> None:
    ctx = _fake_ctx(delay=0.05)
    ctx.ledger.record("retrieve", None, "embed", 7, 0)
    task = asyncio.create_task(partial_usage.record_cancelled_usage(ctx))  # type: ignore[arg-type]
    await asyncio.sleep(0.01)
    task.cancel()
    assert await task is False
    await asyncio.sleep(0.1)
    assert len(ctx.rows) == 1
