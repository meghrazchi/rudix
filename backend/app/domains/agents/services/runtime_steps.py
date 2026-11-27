"""The plan-act-observe step loop of an agent run (split from ``runtime.py``, R06-13).

``execute_steps(rt, loop, start_sequence)`` runs the planned tool selections from
``start_sequence`` on: budget checks before and after every step, cancellation checks,
argument resolution, one ``AgentToolExecutor`` call per step (authorization, payload and
output budgets, redaction, and safe errors stay inside the executor), and the step row
updates. It returns the run result; terminal transitions go through ``runtime_outcome``.

Worker mode (R06-13) adds three things, all absent inline: ``checkpoint`` (commit and renew
the lease) after a step row is running, after the tool call returned, and after the step
ended, so a resumed task finds every finished tool call; ``existing_steps``, the rows a
previous task left running or waiting for approval, which are reused instead of inserted
again (``agent_steps`` is unique per run and sequence); and ``base_elapsed_ms``, the
runtime earlier tasks already spent, so the runtime budget spans the whole run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_agent_event
from app.domains.agents.schemas import (
    AgentBudgetConfig,
    AgentRuntimeError,
    AgentRuntimeRequest,
    AgentRuntimeResult,
    PlannedToolSelection,
    ToolCall,
    ToolEffectPolicy,
    ToolErrorCode,
    ToolResult,
)
from app.domains.agents.services.run_stream import (
    STEP_COMPLETED,
    STEP_STARTED,
    NullRunEvents,
    RunEventSink,
)
from app.domains.agents.services.runtime_context import _RuntimeContext
from app.models.agent import AgentStep
from app.models.enums import AgentRunStatus, AgentStepStatus

if TYPE_CHECKING:
    from app.domains.agents.services.runtime import AgentRuntime


@dataclass
class StepLoop:
    """Everything one pass of the step loop needs."""

    session: AsyncSession
    principal: AuthenticatedPrincipal
    run_id: UUID
    organization_id: UUID
    user_id: UUID
    request: AgentRuntimeRequest
    plan: list[PlannedToolSelection]
    budget: AgentBudgetConfig
    context: _RuntimeContext
    request_id: str | None
    started_perf: float
    cancel_signal: Callable[[], bool] | None = None
    events: RunEventSink = field(default_factory=NullRunEvents)
    checkpoint: Callable[[], Awaitable[None]] | None = None
    existing_steps: dict[int, AgentStep] = field(default_factory=dict)
    base_elapsed_ms: int = 0

    def elapsed_ms(self) -> int:
        return self.base_elapsed_ms + int((perf_counter() - self.started_perf) * 1000)

    async def save(self) -> None:
        if self.checkpoint is not None:
            await self.checkpoint()

    async def emit_step(
        self, event: str, sequence: int, selection: PlannedToolSelection, **extra: Any
    ) -> None:
        await self.events.emit(
            event,
            {
                "sequence": sequence,
                "step_name": selection.step_name,
                "tool_name": selection.tool_name,
                **extra,
            },
        )


def side_effect_idempotency_key(run_id: UUID, sequence: int, tool_name: str) -> str:
    """Stable per run, step, and tool: a resumed run reuses the key of the first attempt."""
    return f"{run_id}:{sequence}:{tool_name}"


async def _fail(rt: AgentRuntime, loop: StepLoop, **kwargs: Any) -> AgentRuntimeResult:
    return await rt._fail_run(
        session=loop.session,
        run_id=loop.run_id,
        organization_id=loop.organization_id,
        user_id=loop.user_id,
        context=loop.context,
        request_id=loop.request_id,
        **kwargs,
    )


async def _cancel(rt: AgentRuntime, loop: StepLoop, reason: str) -> AgentRuntimeResult:
    return await rt._cancel_run(
        session=loop.session,
        run_id=loop.run_id,
        organization_id=loop.organization_id,
        user_id=loop.user_id,
        context=loop.context,
        request_id=loop.request_id,
        reason=reason,
    )


async def _check_before_step(rt: AgentRuntime, loop: StepLoop) -> AgentRuntimeResult | None:
    elapsed_ms = loop.elapsed_ms()
    budget_error = rt._check_budget_before_step(
        budget=loop.budget,
        context=loop.context,
        elapsed_ms=elapsed_ms,
    )
    if budget_error is not None:
        return await _fail(
            rt,
            loop,
            code="budget_exceeded",
            message=budget_error,
            details={"elapsed_ms": elapsed_ms},
        )
    if loop.cancel_signal is not None and loop.cancel_signal():
        return await _cancel(rt, loop, "cancelled_by_signal")
    if await rt._is_cancelled_run(
        session=loop.session,
        run_id=loop.run_id,
        organization_id=loop.organization_id,
    ):
        return await _cancel(rt, loop, "cancelled_in_persistence")
    return None


async def _wait_for_approval(
    rt: AgentRuntime,
    loop: StepLoop,
    *,
    step_id: UUID,
    selection: PlannedToolSelection,
    tool_result: ToolResult,
    step_started_perf: float,
) -> AgentRuntimeResult:
    error = tool_result.error
    assert error is not None
    context = loop.context
    pending_approval_id = error.details.get("approval_id")
    await rt._repository.update_agent_step(
        loop.session,
        agent_step_id=step_id,
        organization_id=loop.organization_id,
        status=AgentStepStatus.waiting_approval.value,
        outputs={},
        metrics={"latency_ms": tool_result.latency_ms or 0},
        error_message=error.safe_message,
        error_details=error.model_dump(),
        completed_at=datetime.now(tz=UTC),
        duration_ms=int((perf_counter() - step_started_perf) * 1000),
    )
    await rt._repository.update_agent_run(
        loop.session,
        agent_run_id=loop.run_id,
        organization_id=loop.organization_id,
        status=AgentRunStatus.waiting_approval.value,
        observations={
            "pending_approval_id": pending_approval_id,
            "pending_tool_name": selection.tool_name,
            "steps_executed": context.steps_executed,
            "tool_calls_executed": context.tool_calls_executed,
        },
    )
    log_agent_event(
        event="agent.runtime.waiting_approval",
        organization_id=str(loop.organization_id),
        user_id=str(loop.user_id),
        run_id=str(loop.run_id),
        pending_approval_id=pending_approval_id,
        pending_tool_name=selection.tool_name,
        steps_executed=context.steps_executed,
        tool_calls_executed=context.tool_calls_executed,
    )
    await rt._record_runtime_usage_event(
        session=loop.session,
        organization_id=loop.organization_id,
        user_id=loop.user_id,
        run_id=loop.run_id,
        request_id=loop.request_id,
        context=context,
        status=AgentRunStatus.waiting_approval.value,
        confidence=None,
        not_found=None,
        error_code="approval_required",
        runtime_ms=loop.elapsed_ms(),
    )
    return AgentRuntimeResult(
        run_id=str(loop.run_id),
        status=AgentRunStatus.waiting_approval.value,
        steps_executed=context.steps_executed,
        tool_calls_executed=context.tool_calls_executed,
        total_tokens=context.total_tokens,
        total_cost_usd=context.total_cost_usd,
        outcome=None,
        error=AgentRuntimeError(
            code=error.code.value,
            message=error.safe_message,
            retryable=False,
            request_id=loop.request_id,
            details=error.details,
        ),
    )


async def _fail_step(
    rt: AgentRuntime,
    loop: StepLoop,
    *,
    step_id: UUID,
    sequence: int,
    selection: PlannedToolSelection,
    tool_result: ToolResult,
    step_started_perf: float,
) -> AgentRuntimeResult:
    error = tool_result.error
    await rt._repository.update_agent_step(
        loop.session,
        agent_step_id=step_id,
        organization_id=loop.organization_id,
        status=AgentStepStatus.failed.value,
        outputs={},
        metrics={"latency_ms": tool_result.latency_ms or 0},
        error_message=error.safe_message if error is not None else None,
        error_details=error.model_dump() if error is not None else {},
        completed_at=datetime.now(tz=UTC),
        duration_ms=int((perf_counter() - step_started_perf) * 1000),
    )
    error_code = error.code.value if error is not None else "internal_error"
    log_agent_event(
        event="agent.step.failed",
        organization_id=str(loop.organization_id),
        user_id=str(loop.user_id),
        run_id=str(loop.run_id),
        tool_name=selection.tool_name,
        step_name=selection.step_name,
        sequence=sequence,
        error_code=error_code,
        latency_ms=tool_result.latency_ms or 0,
    )
    return await _fail(
        rt,
        loop,
        code=error_code,
        message=error.safe_message if error is not None else "Tool execution failed",
        details=error.details if error is not None else {},
    )


async def _record_success(
    rt: AgentRuntime,
    loop: StepLoop,
    *,
    step_id: UUID,
    sequence: int,
    selection: PlannedToolSelection,
    tool_result: ToolResult,
    step_started_perf: float,
) -> AgentRuntimeResult | None:
    """Observe a successful step; a result when the after-step budget stops the run."""
    context = loop.context
    output = tool_result.output or {}
    context.latest_output = output
    context.steps_executed += 1
    rt._observe_after_step(selection=selection, output=output, context=context)
    usage = rt._extract_usage(output)
    context.total_tokens += usage["total_tokens"]
    context.total_cost_usd += usage["total_cost_usd"]
    metrics = {
        "latency_ms": tool_result.latency_ms or 0,
        "total_tokens": context.total_tokens,
        "total_cost_usd": str(context.total_cost_usd),
    }
    duration_ms = int((perf_counter() - step_started_perf) * 1000)

    step_budget_error = rt._check_budget_after_step(budget=loop.budget, context=context)
    if step_budget_error is not None:
        await rt._repository.update_agent_step(
            loop.session,
            agent_step_id=step_id,
            organization_id=loop.organization_id,
            status=AgentStepStatus.failed.value,
            outputs=output,
            metrics=metrics,
            error_message=step_budget_error,
            error_details={"code": "budget_exceeded"},
            completed_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )
        log_agent_event(
            event="agent.step.failed",
            organization_id=str(loop.organization_id),
            user_id=str(loop.user_id),
            run_id=str(loop.run_id),
            tool_name=selection.tool_name,
            step_name=selection.step_name,
            sequence=sequence,
            error_code="budget_exceeded",
            latency_ms=tool_result.latency_ms or 0,
            total_tokens=context.total_tokens,
            total_cost_usd=str(context.total_cost_usd),
        )
        return await _fail(rt, loop, code="budget_exceeded", message=step_budget_error, details={})

    await rt._repository.update_agent_step(
        loop.session,
        agent_step_id=step_id,
        organization_id=loop.organization_id,
        status=AgentStepStatus.completed.value,
        outputs=output,
        metrics=metrics,
        completed_at=datetime.now(tz=UTC),
        duration_ms=duration_ms,
    )
    confidence_score = (
        output.get("confidence", {}).get("score")
        if isinstance(output.get("confidence"), dict)
        else None
    )
    log_agent_event(
        event="agent.step.completed",
        organization_id=str(loop.organization_id),
        user_id=str(loop.user_id),
        run_id=str(loop.run_id),
        tool_name=selection.tool_name,
        step_name=selection.step_name,
        sequence=sequence,
        latency_ms=tool_result.latency_ms or 0,
        total_tokens=context.total_tokens,
        total_cost_usd=str(context.total_cost_usd),
        confidence_score=confidence_score,
    )
    return None


async def _run_step(
    rt: AgentRuntime, loop: StepLoop, sequence: int, selection: PlannedToolSelection
) -> AgentRuntimeResult | None:
    """One step; a result when the run stops here, ``None`` to continue."""
    stopped = await _check_before_step(rt, loop)
    if stopped is not None:
        return stopped
    try:
        arguments = rt._resolve_selection_arguments(selection=selection, context=loop.context)
    except ValueError as exc:
        return await _fail(rt, loop, code="validation_failed", message=str(exc), details={})
    step_started_perf = perf_counter()
    step = await _start_step(rt, loop, sequence, selection, arguments)
    await loop.emit_step(STEP_STARTED, sequence, selection, status="running")
    await loop.save()
    spec = rt._registry.get_spec(selection.tool_name)
    idempotency_key: str | None = None
    if spec is not None and spec.effect_policy is ToolEffectPolicy.side_effect:
        idempotency_key = side_effect_idempotency_key(loop.run_id, sequence, selection.tool_name)
    tool_call = ToolCall(
        run_id=str(loop.run_id),
        tool_name=selection.tool_name,
        organization_id=str(loop.organization_id),
        user_id=str(loop.user_id),
        arguments=arguments,
        idempotency_key=idempotency_key,
        approval_id=loop.request.approval_ids.get(selection.tool_name),
    )
    tool_result = await rt._executor.execute(
        session=loop.session,
        call=tool_call,
        principal=loop.principal,
        request_id=loop.request_id,
    )
    loop.context.tool_calls_executed += 1
    # Worker mode: the finished tool call is committed before the step ends, so a task that
    # dies now is resumed with the call's result instead of running the tool again.
    await loop.save()
    result = await _finish_step(rt, loop, step, sequence, selection, tool_result, step_started_perf)
    if result is None or result.status != AgentRunStatus.waiting_approval.value:
        status = "completed" if result is None else "failed"
        await loop.emit_step(STEP_COMPLETED, sequence, selection, status=status)
    await loop.save()
    return result


async def _start_step(
    rt: AgentRuntime,
    loop: StepLoop,
    sequence: int,
    selection: PlannedToolSelection,
    arguments: dict[str, Any],
) -> AgentStep:
    inputs = {
        "tool_name": selection.tool_name,
        "arguments": arguments,
        "rationale": selection.rationale,
    }
    existing = loop.existing_steps.pop(sequence, None)
    if existing is not None:
        return await rt._worker_repository.reset_step_for_retry(
            loop.session, step=existing, inputs=inputs, started_at=datetime.now(tz=UTC)
        )
    return await rt._repository.create_agent_step(
        loop.session,
        agent_run_id=loop.run_id,
        organization_id=loop.organization_id,
        user_id=loop.user_id,
        sequence=sequence,
        step_name=selection.step_name,
        status=AgentStepStatus.running.value,
        inputs=inputs,
        started_at=datetime.now(tz=UTC),
    )


async def _finish_step(
    rt: AgentRuntime,
    loop: StepLoop,
    step: AgentStep,
    sequence: int,
    selection: PlannedToolSelection,
    tool_result: ToolResult,
    step_started_perf: float,
) -> AgentRuntimeResult | None:
    if not tool_result.success:
        error = tool_result.error
        if error is not None and error.code == ToolErrorCode.approval_required:
            return await _wait_for_approval(
                rt,
                loop,
                step_id=step.id,
                selection=selection,
                tool_result=tool_result,
                step_started_perf=step_started_perf,
            )
        return await _fail_step(
            rt,
            loop,
            step_id=step.id,
            sequence=sequence,
            selection=selection,
            tool_result=tool_result,
            step_started_perf=step_started_perf,
        )
    return await _record_success(
        rt,
        loop,
        step_id=step.id,
        sequence=sequence,
        selection=selection,
        tool_result=tool_result,
        step_started_perf=step_started_perf,
    )


async def execute_steps(
    rt: AgentRuntime, loop: StepLoop, start_sequence: int = 1
) -> AgentRuntimeResult:
    for sequence, selection in enumerate(loop.plan, start=1):
        if sequence < start_sequence:
            continue
        stopped = await _run_step(rt, loop, sequence, selection)
        if stopped is not None:
            return stopped
    return await rt._complete_run(
        session=loop.session,
        principal=loop.principal,
        run_id=loop.run_id,
        organization_id=loop.organization_id,
        user_id=loop.user_id,
        context=loop.context,
        request_id=loop.request_id,
        runtime_ms=loop.elapsed_ms(),
    )
