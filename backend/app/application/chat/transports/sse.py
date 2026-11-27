"""Server-Sent Events adapter of the chat pipeline: ``POST /chat/query/stream`` (R05-03).

The same ``ChatPipeline`` as ``POST /chat`` and ``/chat/ws`` runs in a background task with
one short database session per phase (``SessionLocal`` from the chat module, read at call
time). Stages 1-3 (authorisation, guard, configuration) finish before the response starts,
so their refusals keep the HTTP status and detail of ``POST /chat`` (403 plan limit, 404
document or session). Every later failure becomes one ``chat.error`` event with the
WebSocket's safe codes.

Frames: ``id: <sequence>`` / ``event: <event>`` / ``data: <ChatWSOutboundEvent JSON>``,
plus a ``: keep-alive`` comment when nothing was sent for a heartbeat interval. A client
disconnect (or the response being torn down) cancels the run, which closes the provider
stream and records partial usage (``partial_usage.py``).
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import uuid4

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.application.chat.pipeline.context import ChatContext, RunIds
from app.application.chat.pipeline.deps import (
    ChatPipelineDeps,
    EnsureQuota,
    SessionFactory,
    default_deps,
)
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.events import ChatEvent
from app.application.chat.pipeline.pipeline import ChatPipeline, _end_read_phase, default_stages
from app.application.chat.pipeline.request_helpers import _principal_user_and_org
from app.application.chat.pipeline.runner import Stage, StageRunner
from app.application.chat.pipeline.sessions import ShortSessionScope
from app.application.chat.pipeline.stages.resolve_config import ResolveConfigStage
from app.application.chat.transports.http import build_chat_query_response
from app.application.chat.transports.ws import WsEmitter, WsSequence, emit_pipeline_failure
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.domains.chat.schemas.chat_ws import ChatWSOutboundEvent

SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
# Stages 1-3 end with configuration resolution; refusals up to here are HTTP errors.
PRE_STREAM_LAST_STAGE = ResolveConfigStage.name
_CANCEL_WAIT_SECONDS = 5.0

# Strong references to running SSE pipelines (asyncio keeps only weak ones).
_active_runs: set[asyncio.Task[None]] = set()


SSE_KEEPALIVE_FRAME = ": keep-alive\n\n"


def format_sse_event(event_id: int, event: str, data: str) -> str:
    """One frame of the 0.5.0 framing; also used by the agent run stream (R06-13)."""
    return f"id: {event_id}\nevent: {event}\ndata: {data}\n\n"


def format_sse_frame(event: ChatWSOutboundEvent) -> str:
    return format_sse_event(event.sequence, event.event, event.to_json())


class SseEmitter(WsEmitter):
    """``WsEmitter`` numbering and ids, delivered to a queue instead of a socket."""

    def __init__(
        self,
        queue: "asyncio.Queue[ChatWSOutboundEvent | None]",
        *,
        request_id: str,
        ids: RunIds,
    ) -> None:
        super().__init__(_NoSocket(), request_id=request_id, ids=ids, sequence=WsSequence())
        self._queue = queue

    async def _deliver(self, outbound: ChatWSOutboundEvent) -> None:
        self._queue.put_nowait(outbound)


class _NoSocket:
    async def send_text(self, data: str) -> None:  # pragma: no cover - never called
        return None


class SseResponse(StreamingResponse):
    """Cancels the run whenever the response ends early (disconnect, send failure, or
    cancellation by a middleware task group), whatever the ASGI spec version."""

    def __init__(self, content: AsyncIterator[str], *, run: asyncio.Task[None]) -> None:
        super().__init__(content, media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)
        self.run = run

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # ASGI 2.4+: Starlette does not listen for http.disconnect while streaming (it
        # relies on send failing), so a stalled stream would only notice at the next
        # keep-alive. Listen here and cancel the run at once.
        spec = scope.get("asgi", {}).get("spec_version", "2.0")
        watcher: asyncio.Task[None] | None = None
        if tuple(int(part) for part in spec.split(".")) >= (2, 4):
            watcher = asyncio.create_task(self._cancel_on_disconnect(receive))
        try:
            await super().__call__(scope, receive, send)
        finally:
            if watcher is not None:
                watcher.cancel()
            await cancel_run(self.run)

    async def _cancel_on_disconnect(self, receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                request_cancel(self.run)
                return


def request_cancel(run: asyncio.Task[None]) -> None:
    """Cancel once: a second cancellation would interrupt the partial-usage write."""
    if not run.done() and run.cancelling() == 0:
        run.cancel()


async def cancel_run(run: asyncio.Task[None]) -> None:
    if run.done():
        return
    request_cancel(run)
    try:
        await asyncio.wait_for(asyncio.shield(run), timeout=_CANCEL_WAIT_SECONDS)
    except (asyncio.CancelledError, Exception):
        # The run records partial usage on its own; an outer cancellation lands here.
        pass


async def _frames(
    queue: "asyncio.Queue[ChatWSOutboundEvent | None]", run: asyncio.Task[None]
) -> AsyncIterator[str]:
    keepalive = float(settings.ws_chat_heartbeat_interval_seconds)
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except TimeoutError:
                yield SSE_KEEPALIVE_FRAME
                continue
            if item is None:
                return
            yield format_sse_frame(item)
    finally:
        request_cancel(run)


async def open_sse_query(
    *,
    payload: ChatQueryRequest,
    principal: AuthenticatedPrincipal,
    request_id: str,
    session_factory: SessionFactory,
    ensure_quota: EnsureQuota,
    deps: ChatPipelineDeps = default_deps,
) -> SseResponse:
    """Start the run, wait for stages 1-3, then return the event stream.

    Raises the same ``HTTPException`` as ``POST /chat`` when stages 1-3 refuse the request.
    """
    ids = RunIds()
    if payload.chat_session_id is None:
        # Pre-assigned so every event of the run carries the conversation id (R05-02).
        ids.new_chat_session = True
        ids.chat_session_id = uuid4()
    queue: asyncio.Queue[ChatWSOutboundEvent | None] = asyncio.Queue()
    emitter = SseEmitter(queue, request_id=request_id, ids=ids)
    ready = asyncio.Event()

    async def after_stage(stage: Stage, ctx: ChatContext) -> None:
        await _end_read_phase(stage, ctx)
        if stage.name == PRE_STREAM_LAST_STAGE:
            ready.set()

    pipeline = ChatPipeline(
        replace(deps, session_factory=session_factory, ensure_quota=ensure_quota),
        runner=StageRunner(default_stages(), after_stage=after_stage),
    )
    _, organization_id = _principal_user_and_org(principal)

    async def run() -> None:
        try:
            ctx = await pipeline.run(
                payload,
                principal,
                "sse",
                emitter,
                ShortSessionScope(organization_id=organization_id, session_factory=session_factory),
                request_id,
                ids=ids,
            )
            response = build_chat_query_response(ctx)
            await emitter.emit(
                ChatEvent(
                    type="chat.completed",
                    payload={"response": json.loads(response.model_dump_json())},
                    message_id=response.message_id,
                )
            )
        except Exception as exc:
            if not ready.is_set():
                raise  # answered as an HTTP error by open_sse_query
            await emit_pipeline_failure(emitter, exc, principal, request_id, transport="sse")
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(run())
    _active_runs.add(task)
    task.add_done_callback(_active_runs.discard)
    await emitter.emit(ChatEvent(type="chat.request.received"))
    ready_wait = asyncio.create_task(ready.wait())
    try:
        await asyncio.wait({task, ready_wait}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        ready_wait.cancel()
        await cancel_run(task)
        raise
    ready_wait.cancel()
    if task.done() and not ready.is_set():
        _raise_pre_stream_failure(task)
    log_query_event(
        event="chat.sse.stream_started",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        request_id=request_id,
    )
    return SseResponse(_frames(queue, task), run=task)


def _raise_pre_stream_failure(task: asyncio.Task[None]) -> None:
    exc = task.exception()
    if exc is None:  # pragma: no cover - the run always passes stage 3 when it succeeds
        raise RuntimeError("chat stream ended before stage 3")  # answered as a safe 500
    if isinstance(exc, ChatPipelineError):
        raise exc.to_http_exception() from exc
    raise exc
