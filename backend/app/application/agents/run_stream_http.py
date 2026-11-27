"""``GET /agent/runs/{run_id}/stream``: Server-Sent Events of one agent run (R06-13).

Frames use the 0.5.0 framing of ``app/application/chat/transports/sse.py``
(``id:`` / ``event:`` / ``data:``, plus ``: keep-alive`` comments). The endpoint has already
checked the role, the feature flag, the organisation, and (for members and viewers) that
the caller started the run. Two sources, in order:

1. **Redis** (buffer and pub/sub of ``run_stream.RedisRunEvents``): subscribe first, then
   replay the buffer from ``Last-Event-ID`` (events with a larger id), then follow the
   channel. While the channel is idle the run row is read every keep-alive interval, so a
   run the reaper failed (no event published) still ends the stream.
2. **Database polling** when Redis is not configured, fails, or holds no buffer for the run
   (expired, or the run was executed without Redis): every
   ``AGENT_STREAM_POLL_INTERVAL_MS`` the run and its steps are read and every state change
   becomes an event. Ids continue after ``Last-Event-ID``; the first poll sends the run's
   current state, so a reconnecting client may see an event again but never misses one.

The stream ends after a terminal event (``agent.run.completed``, ``.failed``,
``.cancelled``) or after ``AGENT_STREAM_BUFFER_TTL_SECONDS``. Payloads carry ids, statuses,
tool names, counts, and safe error codes only.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.application.chat.transports.sse import (
    SSE_HEADERS,
    SSE_KEEPALIVE_FRAME,
    SSE_MEDIA_TYPE,
    format_sse_event,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_agent_stream_event
from app.db.tenant_context import bind_session_tenant
from app.domains.agents.services.run_stream import (
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STATUS,
    RUN_WAITING_APPROVAL,
    STEP_COMPLETED,
    STEP_STARTED,
    TERMINAL_EVENTS,
    buffer_key,
    build_entry,
    channel_name,
    decode_entry,
)
from app.models.agent import AgentRun, AgentStep
from app.models.enums import AgentRunStatus, AgentStepStatus

logger = get_logger("agent.stream")
_TERMINAL_RUN_EVENTS = {
    AgentRunStatus.completed.value: RUN_COMPLETED,
    AgentRunStatus.failed.value: RUN_FAILED,
    AgentRunStatus.cancelled.value: RUN_CANCELLED,
}
_STEP_ENDED = {AgentStepStatus.completed.value, AgentStepStatus.failed.value}


@dataclass(frozen=True)
class StepState:
    sequence: int
    step_name: str
    status: str
    tool_name: str | None
    error_code: str | None


@dataclass(frozen=True)
class RunState:
    status: str
    steps_executed: int | None
    tool_calls_executed: int | None
    error_code: str | None
    approval_id: str | None
    steps: list[StepState] = field(default_factory=list)


Event = tuple[tuple[Any, ...], str, dict[str, Any]]


def derive_events(state: RunState) -> list[Event]:
    """(dedupe key, event, payload) for every state the run and its steps are in."""
    events: list[Event] = []
    terminal = _TERMINAL_RUN_EVENTS.get(state.status)
    waiting = state.status == AgentRunStatus.waiting_approval.value
    if terminal is None and not waiting:
        events.append((("run", state.status), RUN_STATUS, {"status": state.status}))
    for step in state.steps:
        base = {"sequence": step.sequence, "step_name": step.step_name, "tool_name": step.tool_name}
        events.append((("step", step.sequence, "started"), STEP_STARTED, base))
        if step.status in _STEP_ENDED:
            payload = {**base, "status": step.status, "error_code": step.error_code}
            events.append((("step", step.sequence, step.status), STEP_COMPLETED, payload))
    counts = {
        "status": state.status,
        "steps_executed": state.steps_executed,
        "tool_calls_executed": state.tool_calls_executed,
    }
    if waiting:
        payload = {**counts, "approval_id": state.approval_id}
        events.append((("run", "waiting", state.approval_id), RUN_WAITING_APPROVAL, payload))
    if terminal is not None:
        events.append((("run", state.status), terminal, {**counts, "error_code": state.error_code}))
    return events


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


async def load_run_state(
    session_factory: Callable[[], Any], *, organization_id: UUID, run_id: UUID
) -> RunState | None:
    """The run's safe state, read in a short session bound to the caller's tenant."""
    async with session_factory() as session:
        bind_session_tenant(session, organization_id)
        run = (
            await session.execute(
                select(
                    AgentRun.status, AgentRun.observations_json, AgentRun.error_details_json
                ).where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
            )
        ).first()
        if run is None:
            return None
        rows = await session.execute(
            select(
                AgentStep.sequence,
                AgentStep.step_name,
                AgentStep.status,
                AgentStep.inputs_json,
                AgentStep.error_details_json,
            )
            .where(AgentStep.agent_run_id == run_id, AgentStep.organization_id == organization_id)
            .where(AgentStep.sequence >= 1)
            .order_by(AgentStep.sequence.asc())
        )
        steps = [
            StepState(
                sequence=int(row[0]),
                step_name=str(row[1]),
                status=str(row[2]),
                tool_name=_str_or_none((row[3] or {}).get("tool_name")),
                error_code=_str_or_none((row[4] or {}).get("code")),
            )
            for row in rows.all()
        ]
        await session.commit()
    observations = run[1] or {}
    errors = run[2] or {}
    return RunState(
        status=str(run[0]),
        steps_executed=_int_or_none(observations.get("steps_executed")),
        tool_calls_executed=_int_or_none(observations.get("tool_calls_executed")),
        error_code=_str_or_none(errors.get("code")),
        approval_id=_str_or_none(observations.get("pending_approval_id")),
        steps=steps,
    )


class RunStreamReader:
    def __init__(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        last_event_id: int,
        redis: Any,
        load_state: Callable[[], Awaitable[RunState | None]],
    ) -> None:
        self.organization_id = organization_id
        self.run_id = run_id
        self.last_id = max(0, last_event_id)
        self.redis = redis
        self.load_state = load_state
        self.finished = False
        self.source = "database"
        self._deadline = 0.0

    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    def _frame(self, event_id: int, event: str, data: str, source: str) -> str:
        self.last_id = event_id
        if event in TERMINAL_EVENTS:
            self.finished = True
        record_agent_stream_event(source, "streamed")
        return format_sse_event(event_id, event, data)

    def _accept(self, raw: Any) -> str | None:
        entry = decode_entry(raw)
        if entry is None or int(entry["id"]) <= self.last_id:
            return None
        return self._frame(int(entry["id"]), str(entry["event"]), json.dumps(entry), "redis")

    async def frames(self) -> AsyncIterator[str]:
        self._deadline = self._now() + settings.agent_stream_buffer_ttl_seconds
        if self.redis is not None:
            try:
                async for frame in self._redis_frames():
                    yield frame
            except Exception as exc:
                logger.warning(
                    "agent.stream.redis_fallback",
                    run_id=str(self.run_id),
                    organization_id=str(self.organization_id),
                    error=exc.__class__.__name__,
                )
            if self.finished:
                return
        self.source = "database"
        async for frame in self._database_frames():
            yield frame

    async def _replay(self, key: str) -> AsyncIterator[str]:
        for raw in await self.redis.lrange(key, 0, -1):
            frame = self._accept(raw)
            if frame is not None:
                yield frame
                if self.finished:
                    return

    async def _redis_frames(self) -> AsyncIterator[str]:
        key = buffer_key(self.organization_id, self.run_id)
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel_name(self.organization_id, self.run_id))
        try:
            if not await self.redis.exists(key):
                return  # no buffer: the database has the whole history
            self.source = "redis"
            async for frame in self._replay(key):
                yield frame
            poll = settings.agent_stream_poll_interval_ms / 1000
            idle = 0.0
            while not self.finished and self._now() < self._deadline:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=poll)
                if message is not None:
                    idle = 0.0
                    accepted = self._accept(message.get("data"))
                    if accepted is not None:
                        yield accepted
                    continue
                idle += poll
                if idle < settings.agent_stream_keepalive_seconds:
                    continue
                idle = 0.0
                yield SSE_KEEPALIVE_FRAME
                async for frame in self._end_if_terminal(key):
                    yield frame
            self.finished = True
        finally:
            await _close_pubsub(pubsub)

    async def _end_if_terminal(self, key: str) -> AsyncIterator[str]:
        """A terminal run whose event never arrived (the reaper failed it) ends the stream."""
        state = await self.load_state()
        if state is not None and state.status not in _TERMINAL_RUN_EVENTS:
            return
        async for frame in self._replay(key):
            yield frame
        if self.finished:
            return
        if state is None:
            self.finished = True
            return
        for _, event, payload in derive_events(state):
            if event in TERMINAL_EVENTS:
                entry = build_entry(self.last_id + 1, event, self.run_id, payload)
                yield self._frame(self.last_id + 1, event, entry, "database")
                return

    async def _database_frames(self) -> AsyncIterator[str]:
        sent: set[tuple[Any, ...]] = set()
        poll = settings.agent_stream_poll_interval_ms / 1000
        idle = 0.0
        while True:
            state = await self.load_state()
            if state is None:
                self.finished = True
                return
            for key, event, payload in derive_events(state):
                if key in sent:
                    continue
                sent.add(key)
                idle = 0.0
                event_id = self.last_id + 1
                entry = build_entry(event_id, event, self.run_id, payload)
                yield self._frame(event_id, event, entry, "database")
                if self.finished:
                    return
            if self._now() >= self._deadline:
                return
            await asyncio.sleep(poll)
            idle += poll
            if idle >= settings.agent_stream_keepalive_seconds:
                idle = 0.0
                yield SSE_KEEPALIVE_FRAME


async def _close_pubsub(pubsub: Any) -> None:
    for method in ("unsubscribe", "aclose"):
        call = getattr(pubsub, method, None)
        if call is None:
            continue
        try:
            await call()
        except Exception:
            pass


def parse_last_event_id(raw: str | None) -> int:
    if raw is None:
        return 0
    try:
        return max(0, int(raw.strip()))
    except ValueError:
        return 0


def stream_response(reader: RunStreamReader) -> Any:
    from starlette.responses import StreamingResponse

    return StreamingResponse(reader.frames(), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)
