"""Agent run events for ``GET /agent/runs/{run_id}/stream`` (R06-13).

The runtime emits one event per state change of a run:

=============================  ======================================================
Event                          When
=============================  ======================================================
``agent.run.status``           queued (API, worker mode) or running (a task took the lease)
``agent.step.started``         a step row is running
``agent.step.completed``       a step ended (``status`` completed or failed)
``agent.run.waiting_approval`` a tool needs human approval (``approval_id``)
``agent.run.completed``        terminal
``agent.run.failed``           terminal (``error_code``)
``agent.run.cancelled``        terminal
=============================  ======================================================

``RedisRunEvents`` appends each event to a Redis list (the replay buffer, TTL
``AGENT_STREAM_BUFFER_TTL_SECONDS`` after the last write) and publishes it on a channel.
Both keys contain the organisation and the run, and the endpoint builds them from the
caller's organisation, so another organisation's run can never be read. Event ids come from
an ``INCR`` counter next to the list, so they increase across worker tasks of the same run
(only one task holds the run's lease at a time).

Payloads carry ids, statuses, tool names, counts, and safe error codes only
(``SAFE_PAYLOAD_KEYS``): never document text, prompts, or tool outputs. A failing Redis
never fails the run: the sink stops writing and counts the failure.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_agent_stream_event
from app.domains.agents.schemas import AgentRuntimeResult
from app.models.enums import AgentRunStatus

logger = get_logger("agent.stream")

RUN_STATUS = "agent.run.status"
STEP_STARTED = "agent.step.started"
STEP_COMPLETED = "agent.step.completed"
RUN_WAITING_APPROVAL = "agent.run.waiting_approval"
RUN_COMPLETED = "agent.run.completed"
RUN_FAILED = "agent.run.failed"
RUN_CANCELLED = "agent.run.cancelled"
TERMINAL_EVENTS = frozenset({RUN_COMPLETED, RUN_FAILED, RUN_CANCELLED})
TERMINAL_STATUSES = frozenset(
    {AgentRunStatus.completed.value, AgentRunStatus.failed.value, AgentRunStatus.cancelled.value}
)
_RESULT_EVENTS = {
    AgentRunStatus.completed.value: RUN_COMPLETED,
    AgentRunStatus.failed.value: RUN_FAILED,
    AgentRunStatus.cancelled.value: RUN_CANCELLED,
    AgentRunStatus.waiting_approval.value: RUN_WAITING_APPROVAL,
}
SAFE_PAYLOAD_KEYS = frozenset(
    {
        "status",
        "sequence",
        "step_name",
        "tool_name",
        "steps_executed",
        "tool_calls_executed",
        "error_code",
        "approval_id",
        "resume_count",
    }
)


def safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Only allow-listed keys with scalar values."""
    return {
        key: value
        for key, value in payload.items()
        if key in SAFE_PAYLOAD_KEYS and (value is None or isinstance(value, str | int | bool))
    }


def _base_key(organization_id: UUID | str, run_id: UUID | str) -> str:
    env = settings.environment.value
    return f"rudix:{env}:agent:run:v1:{organization_id}:{run_id}"


def buffer_key(organization_id: UUID | str, run_id: UUID | str) -> str:
    return f"{_base_key(organization_id, run_id)}:events"


def sequence_key(organization_id: UUID | str, run_id: UUID | str) -> str:
    return f"{_base_key(organization_id, run_id)}:seq"


def channel_name(organization_id: UUID | str, run_id: UUID | str) -> str:
    return f"{_base_key(organization_id, run_id)}:channel"


def build_entry(event_id: int, event: str, run_id: UUID | str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "id": event_id,
            "event": event,
            "run_id": str(run_id),
            "payload": safe_payload(payload),
            "emitted_at": datetime.now(tz=UTC).isoformat(),
        },
        separators=(",", ":"),
    )


def decode_entry(raw: Any) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, AttributeError, TypeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("id"), int):
        return None
    if not isinstance(value.get("event"), str):
        return None
    return value


class RunEventSink(Protocol):
    async def emit(self, event: str, payload: dict[str, Any]) -> None: ...


class NullRunEvents:
    """Sink used when Redis is not configured (the stream then polls the database)."""

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        del event, payload


# Run-level events also go to the per-user realtime stream (R07-07) as ``agent.run``.
_RUN_LEVEL_EVENTS = frozenset({RUN_STATUS, RUN_WAITING_APPROVAL}) | TERMINAL_EVENTS


class RedisRunEvents:
    """Buffer and publish one run's events; the run's lease holder is the only writer."""

    def __init__(
        self,
        redis: Any,
        *,
        organization_id: UUID | str,
        run_id: UUID | str,
        user_id: UUID | str | None = None,
    ) -> None:
        self._redis = redis
        self._organization_id = organization_id
        self._run_id = run_id
        self._user_id = user_id
        self.failed = False
        self.emitted = 0

    async def _publish_realtime(self, event: str, payload: dict[str, Any]) -> None:
        status = payload.get("status")
        if event not in _RUN_LEVEL_EVENTS or not isinstance(status, str):
            return
        from app.application.realtime.publisher import publish_now
        from app.domains.realtime.events import agent_run_event

        await publish_now(
            agent_run_event(
                organization_id=self._organization_id,
                run_id=self._run_id,
                status=status,
                user_id=self._user_id,
            ),
            redis=self._redis,
        )

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        await self._publish_realtime(event, payload)
        if self.failed:
            return
        ttl_ms = settings.agent_stream_buffer_ttl_seconds * 1000
        list_key = buffer_key(self._organization_id, self._run_id)
        seq_key = sequence_key(self._organization_id, self._run_id)
        try:
            event_id = int(await self._redis.incr(seq_key))
            entry = build_entry(event_id, event, self._run_id, payload)
            await self._redis.rpush(list_key, entry)
            await self._redis.pexpire(list_key, ttl_ms)
            await self._redis.pexpire(seq_key, ttl_ms)
            await self._redis.publish(channel_name(self._organization_id, self._run_id), entry)
        except Exception as exc:
            self.failed = True
            record_agent_stream_event("redis", "publish_failed")
            logger.warning(
                "agent.stream.publish_failed",
                run_id=str(self._run_id),
                organization_id=str(self._organization_id),
                error=exc.__class__.__name__,
            )
            return
        self.emitted += 1
        record_agent_stream_event("redis", "published")


def build_run_events(
    redis: Any,
    *,
    organization_id: UUID | str,
    run_id: UUID | str,
    user_id: UUID | str | None = None,
) -> RunEventSink:
    if redis is None:
        return NullRunEvents()
    return RedisRunEvents(redis, organization_id=organization_id, run_id=run_id, user_id=user_id)


def result_event(result: AgentRuntimeResult) -> tuple[str, dict[str, Any]] | None:
    """The event that reports where a runtime call left the run."""
    event = _RESULT_EVENTS.get(result.status)
    if event is None:
        return None
    payload: dict[str, Any] = {
        "status": result.status,
        "steps_executed": result.steps_executed,
        "tool_calls_executed": result.tool_calls_executed,
    }
    if result.error is not None:
        payload["error_code"] = result.error.code
        approval_id = result.error.details.get("approval_id")
        if event == RUN_WAITING_APPROVAL and isinstance(approval_id, str):
            payload["approval_id"] = approval_id
    return event, payload


async def emit_result(events: RunEventSink, result: AgentRuntimeResult) -> None:
    resolved = result_event(result)
    if resolved is not None:
        await events.emit(*resolved)
