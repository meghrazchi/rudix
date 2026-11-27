"""WebSocket adapter of the chat pipeline (R05-01): emitter, sequence, and error mapping."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException, WebSocketDisconnect

from app.application.chat.pipeline.context import RunIds
from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.events import ChatEvent
from app.application.chat.pipeline.sessions import ShortSessionScope
from app.application.chat.transports import ws as ws_transport
from app.application.chat.transports.ws import (
    WsEmitter,
    WsSequence,
    as_ws_sequence,
    run_ws_query,
    ws_send,
)
from app.application.chat.ws_auth import WsAuthResult
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.chat.schemas.chat_ws import ChatWSOutboundEvent
from app.interfaces.http import chat as chat_api

pytestmark = [pytest.mark.asyncio]


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(uuid4()),
        organization_id=str(uuid4()),
        roles=["member"],
        auth_provider="app",
    )


class _Socket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


class _BrokenSocket:
    async def send_text(self, data: str) -> None:
        raise RuntimeError("socket closed")


def test_sequence_counter_and_legacy_integer_start() -> None:
    shared = WsSequence()
    assert as_ws_sequence(shared) is shared
    assert [shared.next(), shared.next()] == [1, 2]
    legacy = as_ws_sequence(5)
    assert legacy is not shared
    assert (legacy.value, legacy.next()) == (5, 6)


async def test_ws_send_swallows_socket_errors() -> None:
    await ws_send(_BrokenSocket(), ChatWSOutboundEvent(event="heartbeat.ping"))


async def test_emitter_sets_conversation_and_message_ids_and_numbers_events() -> None:
    socket = _Socket()
    ids = RunIds()
    sequence = WsSequence(10)
    emitter = WsEmitter(socket, request_id="req-1", ids=ids, sequence=sequence)

    await emitter.emit(ChatEvent(type="chat.request.received"))
    ids.chat_session_id = uuid4()
    await emitter.emit(ChatEvent(type="retrieval.started"))
    await emitter.emit(ChatEvent(type="generation.started"))
    await emitter.emit(ChatEvent(type="generation.delta", payload={"text": "Hi"}))
    await emitter.emit(ChatEvent(type="chat.completed", message_id="explicit"))
    await emitter.emit_error("retrieval_failed", {"k": "v"})

    assert [e["sequence"] for e in socket.sent] == [11, 12, 13, 14, 15, 16]
    assert {e["request_id"] for e in socket.sent} == {"req-1"}
    assert socket.sent[0]["conversation_id"] is None
    assert {e["conversation_id"] for e in socket.sent[1:]} == {str(ids.chat_session_id)}
    message_ids = [e["message_id"] for e in socket.sent]
    assistant = str(ids.assistant_message_id)
    assert message_ids == [None, None, assistant, assistant, "explicit", assistant]
    assert socket.sent[-1]["safe_error_code"] == "retrieval_failed"
    assert socket.sent[-1]["payload"] == {"k": "v"}


async def _run(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> list[dict[str, Any]]:
    async def _failing_run(self: object, *args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(ws_transport.ChatPipeline, "run", _failing_run)
    socket = _Socket()
    await run_ws_query(
        websocket=socket,
        payload={"question": "How much leave?"},
        principal=_principal(),
        request_id="req-err",
        sequence=WsSequence(),
        session_factory=lambda: None,
        ensure_quota=default_deps.ensure_quota,
    )
    return socket.sent


async def test_invalid_payload_is_refused_before_the_pipeline() -> None:
    socket = _Socket()
    await run_ws_query(
        websocket=socket,
        payload={"question": ""},
        principal=_principal(),
        request_id="req-bad",
        sequence=WsSequence(),
        session_factory=lambda: None,
        ensure_quota=default_deps.ensure_quota,
    )
    assert [(e["event"], e["safe_error_code"]) for e in socket.sent] == [
        ("chat.error", "invalid_request")
    ]


@pytest.mark.parametrize(
    ("error", "code", "payload"),
    [
        (
            ChatPipelineError(code="document_not_found", status_code=404, message="x"),
            "document_not_found",
            None,
        ),
        (
            HTTPException(
                status_code=403,
                detail={
                    "code": "plan_limit_exceeded",
                    "quota_type": "questions",
                    "retryable": False,
                    "next_reset_at": None,
                    "current_value": 9,
                },
            ),
            "plan_limit_exceeded",
            {"quota_type": "questions", "retryable": False, "next_reset_at": None},
        ),
        (HTTPException(status_code=503, detail="store down"), "internal_error", None),
        (RuntimeError("secret detail"), "internal_error", None),
    ],
)
async def test_errors_map_to_safe_codes(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    code: str,
    payload: dict[str, Any] | None,
) -> None:
    sent = await _run(monkeypatch, error)
    assert [e["event"] for e in sent] == ["chat.request.received", "chat.error"]
    assert sent[-1]["safe_error_code"] == code
    assert sent[-1]["payload"] == payload
    assert "secret detail" not in json.dumps(sent)


async def test_cancellation_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(asyncio.CancelledError):
        await _run(monkeypatch, asyncio.CancelledError())


def test_scope_needs_exactly_one_session_source() -> None:
    with pytest.raises(ValueError):
        ShortSessionScope(organization_id=uuid4())
    with pytest.raises(ValueError):
        ShortSessionScope(
            organization_id=uuid4(),
            session_factory=lambda: None,
            request_session=object(),  # type: ignore[arg-type]
        )


class _ConnectionSocket:
    """Accepts one chat.start, lets heartbeats interleave, then disconnects."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}
        self.client = None
        self._received = 0

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        return None

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        self._received += 1
        if self._received == 1:
            return json.dumps({"command": "chat.start", "payload": {"question": "hi"}})
        await asyncio.sleep(0.2)
        raise WebSocketDisconnect()


async def test_connection_and_run_share_one_sequence_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[object] = []

    async def fake_auth(**kwargs: Any) -> WsAuthResult:
        return WsAuthResult(principal=_principal(), method="query_token")

    async def fake_pipeline(**kwargs: Any) -> None:
        received.append(kwargs["sequence_start"])
        emitter = WsEmitter(
            kwargs["websocket"],
            request_id=kwargs["request_id"],
            ids=RunIds(),
            sequence=as_ws_sequence(kwargs["sequence_start"]),
        )
        for _ in range(5):
            await emitter.emit(ChatEvent(type="activity.step.update", payload={}))
            await asyncio.sleep(0.02)

    monkeypatch.setattr(settings, "feature_chat_websocket_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "ws_chat_heartbeat_interval_seconds", 0.01)
    monkeypatch.setattr(chat_api, "authenticate_ws_handshake", fake_auth)
    monkeypatch.setattr(chat_api, "_run_ws_chat_pipeline", fake_pipeline)
    socket = _ConnectionSocket()

    await chat_api.chat_websocket(socket, token="tok")  # type: ignore[arg-type]

    assert len(received) == 1 and isinstance(received[0], WsSequence)
    events = [e["event"] for e in socket.sent]
    assert "heartbeat.ping" in events and events.count("activity.step.update") == 5
    sequences = [e["sequence"] for e in socket.sent]
    assert sequences == list(range(1, len(sequences) + 1))
