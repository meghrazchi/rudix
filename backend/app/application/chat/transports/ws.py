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
from collections.abc import Coroutine
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol
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
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.logging import log_query_event
from app.core.metrics import CHAT_WS_DROP_TOTAL
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.domains.chat.schemas.chat_ws import ChatWSOutboundEvent

if TYPE_CHECKING:
    from app.application.chat.transports.resume_buffer import ResumeBuffer


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
        stream_sequences: bool = False,
    ) -> None:
        self._websocket = websocket
        self._request_id = request_id
        self._ids = ids
        self._sequence = sequence
        self._generation_started = False
        # R05-13: WebSocket runs number every event of the assistant message 1, 2, ...
        # (``stream_sequence``, contract 4.2.6); SSE frames leave it unset.
        self._stream_sequences = stream_sequences
        self._stream_sequence = 0

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
        # Every pipeline event is forwarded, generation.final and generation.replace
        # included (R05-03); deltas carry text only.
        if event.type == "generation.started":
            self._generation_started = True
        await self._send(event.type, event.payload, message_id=self._message_id(event))

    async def emit_error(self, code: str, payload: dict[str, Any] | None = None) -> None:
        message_id = str(self._ids.assistant_message_id) if self._generation_started else None
        await self._send("chat.error", payload, message_id=message_id, safe_error_code=code)

    async def _send(
        self,
        event_type: str,
        payload: dict[str, Any] | None,
        *,
        message_id: str | None = None,
        safe_error_code: str | None = None,
    ) -> None:
        outbound = self._outbound(
            event_type, payload, message_id=message_id, safe_error_code=safe_error_code
        )
        await self._deliver(outbound)

    def _outbound(
        self,
        event_type: str,
        payload: dict[str, Any] | None,
        *,
        message_id: str | None = None,
        safe_error_code: str | None = None,
    ) -> ChatWSOutboundEvent:
        stream_sequence: int | None = None
        if self._stream_sequences:
            self._stream_sequence += 1
            stream_sequence = self._stream_sequence
        return ChatWSOutboundEvent(
            event=event_type,  # type: ignore[arg-type]
            request_id=self._request_id,
            conversation_id=self.conversation_id,
            message_id=message_id,
            sequence=self._sequence.next(),
            payload=payload,
            safe_error_code=safe_error_code,
            stream_sequence=stream_sequence,
        )

    async def _deliver(self, outbound: ChatWSOutboundEvent) -> None:
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
    emitter = build_run_emitter(websocket, principal, request_id, ids, sequence)
    try:
        await _run_ws_query(
            emitter=emitter,
            payload=payload,
            principal=principal,
            request_id=request_id,
            ids=ids,
            session_factory=session_factory,
            ensure_quota=ensure_quota,
            deps=deps,
        )
    except asyncio.CancelledError:
        # chat.cancel or the end of the grace window: the buffer gets its terminal event.
        await _buffer_cancelled(emitter)
        raise


async def _run_ws_query(
    *,
    emitter: WsEmitter,
    payload: dict[str, Any],
    principal: AuthenticatedPrincipal,
    request_id: str,
    ids: RunIds,
    session_factory: SessionFactory,
    ensure_quota: EnsureQuota,
    deps: ChatPipelineDeps,
) -> None:
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
    except Exception as exc:
        await emit_pipeline_failure(emitter, exc, principal, request_id, transport="ws")
        return

    response = build_chat_query_response(ctx)
    await emitter.emit(
        ChatEvent(
            type="chat.completed",
            payload={"response": json.loads(response.model_dump_json())},
            message_id=response.message_id,
        )
    )


async def emit_pipeline_failure(
    emitter: WsEmitter,
    exc: Exception,
    principal: AuthenticatedPrincipal,
    request_id: str,
    *,
    transport: str,
) -> None:
    """A failed run as one ``chat.error`` with today's safe codes (WebSocket and SSE)."""
    if isinstance(exc, ChatPipelineError):
        await emitter.emit_error(exc.code, exc.payload)
        return
    if isinstance(exc, HTTPException):
        denial = chat_quota_denial(exc)
        if denial is not None:
            await emitter.emit_error("plan_limit_exceeded", denial)
            log_query_event(
                event="query.rejected.quota_exceeded",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                transport=transport,
                request_id=request_id,
            )
            return
    _log_unhandled(principal, exc)
    await emitter.emit_error("internal_error")


def _log_unhandled(principal: AuthenticatedPrincipal, exc: BaseException) -> None:
    log_query_event(
        event="query.failed.ws_unhandled",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        error=exc.__class__.__name__,
    )


# -- resumable runs (R05-13) --------------------------------------------------------------
# ``chat_websocket`` starts each run with ``start_ws_run``; the run publishes its resume
# buffer on the ``WsRunHandle`` found in its context. When the socket drops mid-run,
# ``keep_run_alive_after_drop`` keeps the run going for the grace window (longer while a
# ``chat.resume`` reader is attached), then cancels it; the pipeline records the partial
# usage of a cancelled run (``partial_usage.py``).


@dataclass
class WsRunHandle:
    """What the connection loop knows about its running command: the resume buffer of a
    ``chat.start`` run, or the buffer key a ``chat.resume`` follows."""

    buffer: "ResumeBuffer | None" = None
    resume_of: str | None = None


def current_ws_run() -> WsRunHandle | None:
    return _CURRENT_RUN.get()


_CURRENT_RUN: ContextVar[WsRunHandle | None] = ContextVar("chat_ws_run_handle", default=None)
# Grace watchers outlive their connection; keep a reference until they finish.
_GRACE_WATCHERS: set[asyncio.Task[None]] = set()


def start_ws_run(run: Coroutine[Any, Any, None], handle: WsRunHandle) -> asyncio.Task[None]:
    """Run ``run`` as a task whose context carries ``handle``."""
    context = copy_context()
    context.run(_CURRENT_RUN.set, handle)
    return asyncio.create_task(run, context=context)


def build_run_emitter(
    websocket: WebSocketLike,
    principal: AuthenticatedPrincipal,
    request_id: str,
    ids: RunIds,
    sequence: WsSequence,
) -> WsEmitter:
    """A ``BufferingEmitter`` when Redis is configured, else a plain ``WsEmitter``; both
    number the run's events with ``stream_sequence``."""
    from app.application.chat.transports.resume_buffer import (
        BufferingEmitter,
        ResumeBuffer,
        resume_key,
    )

    redis = redis_module.redis_client
    if redis is None:
        return WsEmitter(
            websocket, request_id=request_id, ids=ids, sequence=sequence, stream_sequences=True
        )
    user_id, organization_id = _principal_user_and_org(principal)
    buffer = ResumeBuffer(redis, resume_key(organization_id, user_id, ids.assistant_message_id))
    handle = _CURRENT_RUN.get()
    if handle is not None:
        handle.buffer = buffer
    return BufferingEmitter(
        websocket, buffer=buffer, request_id=request_id, ids=ids, sequence=sequence
    )


async def _buffer_cancelled(emitter: WsEmitter) -> None:
    buffer_cancelled = getattr(emitter, "buffer_cancelled", None)
    if buffer_cancelled is None:
        return
    try:
        await asyncio.wait_for(asyncio.shield(buffer_cancelled()), timeout=2.0)
    except BaseException:
        pass


async def forward_ws_cancel(handle: WsRunHandle | None) -> None:
    """``chat.cancel`` while following a resumed run: ask that run to cancel too."""
    from app.application.chat.transports.resume_buffer import request_cancel

    redis = redis_module.redis_client
    if handle is not None and handle.resume_of is not None and redis is not None:
        await request_cancel(redis, handle.resume_of)


def handle_ws_drop(task: asyncio.Task[None], handle: WsRunHandle | None) -> None:
    """The socket closed while ``task`` runs: a ``chat.start`` run gets the grace window;
    a ``chat.resume`` reader (or an unknown task) is cancelled at once."""
    if handle is None or handle.resume_of is not None:
        task.cancel()
        return
    keep_run_alive_after_drop(task, handle)


def keep_run_alive_after_drop(task: asyncio.Task[None], handle: WsRunHandle) -> None:
    """The socket of a running ``chat.start`` dropped: keep the run for the grace window
    (none when the grace is 0 or the run has no working buffer), then cancel it."""
    grace = settings.chat_ws_resume_grace_seconds
    buffer = handle.buffer
    if grace <= 0 or buffer is None or buffer.failed:
        CHAT_WS_DROP_TOTAL.labels(outcome="cancelled_no_grace").inc()
        task.cancel()
        return
    watcher = asyncio.create_task(_watch_dropped_run(task, buffer.key, float(grace)))
    _GRACE_WATCHERS.add(watcher)
    watcher.add_done_callback(_GRACE_WATCHERS.discard)


async def _watch_dropped_run(task: asyncio.Task[None], key: str, grace: float) -> None:
    from app.application.chat.transports.resume_buffer import attached_key, cancel_key, read_flag

    loop = asyncio.get_running_loop()
    redis = redis_module.redis_client
    deadline = loop.time() + grace
    hard_deadline = loop.time() + settings.chat_resume_buffer_ttl_seconds
    poll = settings.chat_resume_poll_ms / 1000
    outcome = "completed"
    while not task.done():
        await asyncio.wait({task}, timeout=poll)
        if task.done():
            break
        now = loop.time()
        if redis is not None and await read_flag(redis, cancel_key(key)):
            outcome = "cancelled"
        elif now >= deadline:
            attached = redis is not None and await read_flag(redis, attached_key(key))
            if attached and now < hard_deadline:
                deadline = now + grace
                continue
            outcome = "cancelled"
        if outcome == "cancelled":
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            break
    CHAT_WS_DROP_TOTAL.labels(outcome=outcome).inc()
    log_query_event(event="chat.ws.dropped_run", outcome=outcome)
