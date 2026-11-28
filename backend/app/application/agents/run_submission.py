"""Worker-mode submission and approval resume of agent runs (R06-13).

With ``AGENT_RUN_EXECUTION=worker``, ``POST /agent/runs`` validates the request and checks
the quota exactly as inline mode does, then:

1. ``create_queued_run`` stores the run as ``queued`` with ``request_snapshot``: the
   validated ``AgentRuntimeRequest`` plus the principal's identity at submission (user,
   organisation, roles; for audit only, the worker re-reads roles from the database);
2. the caller records the quota;
3. ``enqueue_execute`` writes an outbox row for ``agents.run.execute`` (dedupe key: the
   run id) in the same transaction;
4. the caller commits and calls ``publish`` (immediate publication; the outbox relay
   publishes a row left pending).

An approval decided ``approved`` for a run that waits for it moves the run back to
``queued`` and writes an outbox row for ``agents.run.resume`` (dedupe key: the approval id)
in the decision's transaction (``queue_resume``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application import outbox
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_agent_event
from app.domains.agents.repositories import AgentRunRepository
from app.domains.agents.schemas import AgentRuntimeRequest, AgentRuntimeResult
from app.domains.agents.services.run_stream import RUN_STATUS, build_run_events
from app.domains.agents.services.runtime_context import budget_payload, resolve_budget, select_mode
from app.models.agent import AgentRun
from app.models.enums import AgentRunStatus

EXECUTE_TASK = "agents.run.execute"
RESUME_TASK = "agents.run.resume"
SNAPSHOT_VERSION = 1

_repository = AgentRunRepository()


def worker_mode() -> bool:
    return settings.agent_run_execution == "worker"


def build_snapshot(
    *,
    principal: AuthenticatedPrincipal,
    request: AgentRuntimeRequest,
    request_id: str | None,
) -> dict[str, Any]:
    return {
        "version": SNAPSHOT_VERSION,
        "request": request.model_dump(mode="json"),
        "principal": {
            "user_id": principal.user_id,
            "organization_id": principal.organization_id,
            "roles": list(principal.roles),
            "auth_provider": principal.auth_provider,
        },
        "request_id": request_id,
        "submitted_at": datetime.now(tz=UTC).isoformat(),
    }


async def create_queued_run(
    session: AsyncSession,
    *,
    principal: AuthenticatedPrincipal,
    organization_id: UUID,
    user_id: UUID,
    request: AgentRuntimeRequest,
    request_id: str | None,
) -> AgentRun:
    budget = resolve_budget(request.budget)
    return await _repository.create_agent_run(
        session,
        organization_id=organization_id,
        user_id=user_id,
        status=AgentRunStatus.queued.value,
        surface="api",
        objective=request.objective,
        max_steps=budget.max_steps,
        max_parallel_tool_calls=settings.agent_max_parallel_tool_calls,
        budget=budget_payload(budget),
        observations={
            "request_metadata": request.metadata,
            "mode": select_mode(request).value,
            "execution": "worker",
        },
        trace_request_id=request_id,
        request_snapshot=build_snapshot(
            principal=principal, request=request, request_id=request_id
        ),
    )


async def enqueue_execute(session: AsyncSession, *, run: AgentRun) -> UUID | None:
    return await outbox.enqueue(
        session,
        organization_id=run.organization_id,
        task_name=EXECUTE_TASK,
        kwargs={"run_id": str(run.id), "organization_id": str(run.organization_id)},
        queue=settings.celery_queue_agents,
        dedupe_key=f"{EXECUTE_TASK}:{run.id}",
    )


def queued_result(run: AgentRun) -> AgentRuntimeResult:
    return AgentRuntimeResult(run_id=str(run.id), status=AgentRunStatus.queued.value)


async def publish(session: AsyncSession, *, run: AgentRun, redis: Any) -> None:
    """After the commit: tell stream readers the run is queued, then publish the task."""
    events = build_run_events(
        redis, organization_id=run.organization_id, run_id=run.id, user_id=run.user_id
    )
    await events.emit(RUN_STATUS, {"status": AgentRunStatus.queued.value})
    await outbox.publish_after_commit(session)
    log_agent_event(
        event="agent.run.queued",
        organization_id=str(run.organization_id),
        user_id=str(run.user_id) if run.user_id is not None else None,
        run_id=str(run.id),
        queue=settings.celery_queue_agents,
    )


def can_resume(run: AgentRun) -> bool:
    """A waiting run that was submitted in worker mode (it has a request snapshot)."""
    return (
        worker_mode()
        and run.status == AgentRunStatus.waiting_approval.value
        and isinstance(run.request_snapshot, dict)
    )


async def queue_resume(session: AsyncSession, *, run: AgentRun, approval_id: UUID) -> None:
    await _repository.update_agent_run(
        session,
        agent_run_id=run.id,
        organization_id=run.organization_id,
        status=AgentRunStatus.queued.value,
    )
    await outbox.enqueue(
        session,
        organization_id=run.organization_id,
        task_name=RESUME_TASK,
        kwargs={
            "run_id": str(run.id),
            "organization_id": str(run.organization_id),
            "approval_id": str(approval_id),
        },
        queue=settings.celery_queue_agents,
        dedupe_key=f"{RESUME_TASK}:{approval_id}",
    )
