"""Resume a worker-executed agent run after its last completed step (R06-13).

A run that already has its planning step (sequence 0) is resumed, never planned again:

- the plan is read back from the planning step (``outputs.selections``) and the documents
  it runs on from the planning step's ``observation.selected_document_ids``;
- every completed step, in sequence order, is replayed into the runtime state exactly as
  the loop observed it (latest output, selected documents, counters), with token and cost
  totals taken from the step's cumulative metrics;
- the loop continues at the first sequence without a completed step; a row a previous task
  left running or waiting for approval is reused for that sequence;
- earlier tasks' step durations count towards the runtime budget.

Completed steps are never executed again. A side-effect tool whose call finished before the
task died is answered from its stored result by the executor (idempotency key).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.domains.agents.schemas import (
    AgentRuntimeMode,
    AgentRuntimeRequest,
    AgentRuntimeResult,
    PlannedToolSelection,
)
from app.domains.agents.services.run_stream import RunEventSink
from app.domains.agents.services.runtime_context import _RuntimeContext, select_mode
from app.domains.agents.services.runtime_steps import StepLoop, execute_steps
from app.models.agent import AgentRun, AgentStep
from app.models.enums import AgentStepStatus

if TYPE_CHECKING:
    from app.domains.agents.services.runtime import AgentRuntime


def _mode(run: AgentRun, request: AgentRuntimeRequest) -> AgentRuntimeMode:
    stored = (run.observations_json or {}).get("mode")
    try:
        return AgentRuntimeMode(str(stored))
    except ValueError:
        return select_mode(request)


def _decimal(value: Any) -> Decimal:
    try:
        return max(Decimal(str(value)), Decimal("0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def restore_context(
    rt: AgentRuntime,
    *,
    run: AgentRun,
    request: AgentRuntimeRequest,
    planning: AgentStep,
    plan: list[PlannedToolSelection],
    steps: list[AgentStep],
) -> tuple[_RuntimeContext, int]:
    """The runtime state after the completed steps, and the first sequence to run."""
    observation = planning.observation_json or {}
    selected = observation.get("selected_document_ids")
    context = _RuntimeContext(
        mode=_mode(run, request),
        question=request.question or request.objective,
        selected_document_ids=[str(item) for item in selected]
        if isinstance(selected, list)
        else list(request.document_ids),
    )
    next_sequence = 1
    for step in steps:
        if step.sequence != next_sequence or next_sequence > len(plan):
            break
        if step.status != AgentStepStatus.completed.value:
            break
        output = dict(step.outputs_json or {})
        context.latest_output = output
        context.steps_executed += 1
        context.tool_calls_executed += 1
        rt._observe_after_step(selection=plan[step.sequence - 1], output=output, context=context)
        metrics = step.metrics_json or {}
        context.total_tokens = max(int(metrics.get("total_tokens") or 0), 0)
        context.total_cost_usd = _decimal(metrics.get("total_cost_usd", "0"))
        next_sequence += 1
    return context, next_sequence


async def resume_steps(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    run: AgentRun,
    request: AgentRuntimeRequest,
    planning: AgentStep,
    steps: list[AgentStep],
    request_id: str | None,
    events: RunEventSink,
    checkpoint: Callable[[], Awaitable[None]],
) -> AgentRuntimeResult:
    plan = [
        PlannedToolSelection.model_validate(item)
        for item in (planning.outputs_json or {}).get("selections", [])
        if isinstance(item, dict)
    ]
    later = sorted((step for step in steps if step.sequence >= 1), key=lambda s: s.sequence)
    context, start_sequence = restore_context(
        rt, run=run, request=request, planning=planning, plan=plan, steps=later
    )
    loop = StepLoop(
        session=session,
        principal=principal,
        run_id=run.id,
        organization_id=run.organization_id,
        user_id=rt._user_uuid(principal),
        request=request,
        plan=plan,
        budget=rt._resolve_budget(request.budget),
        context=context,
        request_id=request_id,
        started_perf=perf_counter(),
        events=events,
        checkpoint=checkpoint,
        existing_steps={step.sequence: step for step in later if step.sequence >= start_sequence},
        base_elapsed_ms=sum(int(step.duration_ms or 0) for step in [planning, *later]),
    )
    return await execute_steps(rt, loop, start_sequence=start_sequence)
