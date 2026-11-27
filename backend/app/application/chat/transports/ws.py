"""WebSocket adapter of the chat pipeline: ``chat.start`` on ``/chat/ws`` (R05-01, R05-02).

``run_ws_query`` validates the command payload, runs the same ``ChatPipeline`` as
``POST /chat`` with one short database session per phase (``SessionLocal`` from the chat
module, read at call time), and forwards every pipeline event through ``WsEmitter``.
Refusals become ``chat.error`` events with today's safe codes; nothing else (no exception
text, no stack, no document text) reaches the client.

``WsSequence`` is the one ``sequence`` counter of a connection: ``chat_websocket`` creates it
and the heartbeat, ``chat.cancel``, and pipeline events all number from it, so sequences
never collide. An ``int`` start (the legacy ``sequence_start`` argument) gets a new counter.
"""

import asyncio
import json
from dataclasses import replace
from typing import Any, Protocol
from uuid import uuid4

from fastapi import HTTPException

from app.application.chat.pipeline.context import RunIds
from app.application.chat.pipeline.deps import (
    ChatPipelineDeps,
    EnsureQuota,
    SessionFactory,
    default_deps,
)
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.events import ChatEvent
from app.application.chat.pipeline.pipeline import ChatPipeline
from app.application.chat.pipeline.request_helpers import _principal_user_and_org
from app.application.chat.pipeline.sessions import ShortSessionScope
from app.application.chat.quota import chat_quota_denial
from app.application.chat.transports.http import build_chat_query_response
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_query_event
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.domains.chat.schemas.chat_ws import ChatWSOutboundEvent


class WebSocketLike(Protocol):
    async def send_text(self, data: str) -> None: ...


class WsSequence:
    """The ``sequence`` counter of one WebSocket connection (single event loop, no lock)."""

    def __init__(self, start: int = 0) -> None:
        self._value = start

    @property
    def value(self) -> int:
        return self._value

    def next(self) -> int:
        self._value += 1
        return self._value


def as_ws_sequence(sequence_start: "int | WsSequence") -> WsSequence:
    """The connection's counter as is, or a new counter after a legacy integer start."""
    if isinstance(sequence_start, WsSequence):
        return sequence_start
    return WsSequence(int(sequence_start))


async def ws_send(websocket: WebSocketLike, event: ChatWSOutboundEvent) -> None:
    """Send one event; a closed or failing socket is ignored (``_ws_send`` semantics)."""
    try:
        await websocket.send_text(event.to_json())
    except Exception:
        pass


class WsEmitter:
    """Turns pipeline ``ChatEvent`` objects into ``ChatWSOutboundEvent`` frames.

    ``conversation_id`` is the run's chat session id once known (pre-assigned for a new
    session, validated for an existing one); ``message_id`` is the pre-assigned assistant
    message id on every event from ``generation.started`` on (plan contract 4.2.6).
    """

    def __init__(
        self,
        websocket: WebSocketLike,
        *,
        request_id: str,
        ids: RunIds,
        sequence: WsSequence,
    ) -> None:
        self._websocket = websocket
        self._request_id = request_id
        self._ids = ids
        self._sequence = sequence
        self._generation_started = False

    @property
    def conversation_id(self) -> str | None:
        chat_session_id = self._ids.chat_session_id
        return str(chat_session_id) if chat_session_id is not None else None

    def _message_id(self, event: ChatEvent) -> str | None:
        if event.message_id is not None:
            return event.message_id
        if self._generation_started:
            return str(self._ids.assistant_message_id)
        return None

    async def emit(self, event: ChatEvent) -> None:
        if event.type == "generation.started":
            self._generation_started = True
        await self._send(event.type, event.payload, message_id=self._message_id(event))

    async def emit_error(self, code: str, payload: dict[str, Any] | None = None) -> None:
        await self._send("chat.error", payload, safe_error_code=code)

    async def _send(
        self,
        event_type: str,
        payload: dict[str, Any] | None,
        *,
        message_id: str | None = None,
        safe_error_code: str | None = None,
    ) -> None:
        outbound = ChatWSOutboundEvent(
            event=event_type,  # type: ignore[arg-type]
            request_id=self._request_id,
            conversation_id=self.conversation_id,
            message_id=message_id,
            sequence=self._sequence.next(),
            payload=payload,
            safe_error_code=safe_error_code,
        )
        await ws_send(self._websocket, outbound)


async def run_ws_query(
    *,
    websocket: WebSocketLike,
    payload: dict[str, Any],
    principal: AuthenticatedPrincipal,
    request_id: str,
    sequence: WsSequence,
    session_factory: SessionFactory,
    ensure_quota: EnsureQuota,
    deps: ChatPipelineDeps = default_deps,
) -> None:
    """Answer one ``chat.start`` command. ``session_factory`` and ``ensure_quota`` are read
    from the chat module at call time so tests that rebind them reach the pipeline."""
    ids = RunIds()
    emitter = WsEmitter(websocket, request_id=request_id, ids=ids, sequence=sequence)
    try:
        query_request = ChatQueryRequest.model_validate(payload)
    except Exception as exc:
        await emitter.emit_error("invalid_request")
        log_query_event(
            event="query.failed.ws_parse",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            error=exc.__class__.__name__,
        )
        return
    if query_request.chat_session_id is None:
        # Pre-assigned so every event of the run carries the conversation id (R05-02).
        ids.new_chat_session = True
        ids.chat_session_id = uuid4()
    await emitter.emit(ChatEvent(type="chat.request.received"))

    pipeline = ChatPipeline(
        replace(deps, session_factory=session_factory, ensure_quota=ensure_quota)
    )
    try:
        _, organization_id = _principal_user_and_org(principal)
        scope = ShortSessionScope(organization_id=organization_id, session_factory=session_factory)
        ctx = await pipeline.run(
            query_request,
            principal,
            "ws",
            emitter,
            scope,
            request_id,
            ids=ids,
        )
    except asyncio.CancelledError:
        raise
    except ChatPipelineError as exc:
        await emitter.emit_error(exc.code, exc.payload)
        return
    except HTTPException as exc:
        denial = chat_quota_denial(exc)
        if denial is None:
            _log_unhandled(principal, exc)
            await emitter.emit_error("internal_error")
            return
        await emitter.emit_error("plan_limit_exceeded", denial)
        log_query_event(
            event="query.rejected.quota_exceeded",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            transport="ws",
            request_id=request_id,
        )
        return
    except Exception as exc:
        _log_unhandled(principal, exc)
        await emitter.emit_error("internal_error")
        return

    response = build_chat_query_response(ctx)
    await emitter.emit(
        ChatEvent(
            type="chat.completed",
            payload={"response": json.loads(response.model_dump_json())},
            message_id=response.message_id,
        )
    )


def _log_unhandled(principal: AuthenticatedPrincipal, exc: BaseException) -> None:
    log_query_event(
        event="query.failed.ws_unhandled",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        error=exc.__class__.__name__,
    )
