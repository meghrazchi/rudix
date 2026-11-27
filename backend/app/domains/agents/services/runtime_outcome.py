"""Terminal transitions of an agent run: complete, fail, cancel (split from ``runtime.py``).

Each transition updates the run row, logs a structured event, records the
``agent.runtime`` usage event, and writes the audit entries. The functions take the
``AgentRuntime`` so its repositories (and test substitutions on the instance) are used.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_agent_event
from app.domains.agents.schemas import (
    AgentRuntimeError,
    AgentRuntimeMode,
    AgentRuntimeOutcome,
    AgentRuntimeResult,
)
from app.domains.agents.services.runtime_context import _RuntimeContext, safe_int
from app.models.enums import AgentRunStatus

if TYPE_CHECKING:
    from app.domains.agents.services.runtime import AgentRuntime


def _counters(context: _RuntimeContext) -> dict[str, Any]:
    return {
        "steps_executed": context.steps_executed,
        "tool_calls_executed": context.tool_calls_executed,
        "blocked_document_instruction_signals": context.blocked_document_instruction_signals,
    }


def _costs(context: _RuntimeContext) -> dict[str, Any]:
    return {
        "total_tokens": context.total_tokens,
        "total_cost_usd": str(context.total_cost_usd),
    }


def build_outcome(*, context: _RuntimeContext) -> AgentRuntimeOutcome:
    output = context.latest_output or {}
    if context.mode is AgentRuntimeMode.answer:
        answer_key = "response"
    elif context.mode is AgentRuntimeMode.summarize:
        answer_key = "summary"
    else:
        answer_key = "comparison"
    return AgentRuntimeOutcome(
        answer=str(output.get(answer_key, "")),
        citations=output.get("citations", []) if isinstance(output.get("citations"), list) else [],
        confidence=output.get("confidence", {})
        if isinstance(output.get("confidence"), dict)
        else {},
        not_found=bool(output.get("not_found", False)),
        mode=context.mode,
    )


def _provider_metadata(latest_output: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """``provider_key`` and ``provider_type`` from the last tool's debug output."""
    debug = latest_output.get("debug") if isinstance(latest_output, dict) else None
    provider_key: str | None = None
    provider_type: str | None = None
    if isinstance(debug, dict):
        raw_key = debug.get("provider_key")
        if isinstance(raw_key, str) and raw_key.strip():
            provider_key = raw_key.strip()
        raw_type = debug.get("provider_type")
        if isinstance(raw_type, str) and raw_type.strip():
            provider_type = raw_type.strip()
    return provider_key, provider_type


async def complete_run(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    run_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    context: _RuntimeContext,
    request_id: str | None,
    runtime_ms: int,
) -> AgentRuntimeResult:
    outcome = build_outcome(context=context)
    run_provider_key, run_provider_type = _provider_metadata(context.latest_output)
    await rt._repository.update_agent_run(
        session,
        agent_run_id=run_id,
        organization_id=organization_id,
        status=AgentRunStatus.completed.value,
        completed_at=datetime.now(tz=UTC),
        outcome=outcome.model_dump(),
        costs=_costs(context),
        total_cost_usd=float(context.total_cost_usd),
        observations={
            "selected_document_ids": context.selected_document_ids,
            **_counters(context),
            "provider_key": run_provider_key,
            "provider_type": run_provider_type,
        },
    )
    confidence = outcome.confidence if isinstance(outcome.confidence, dict) else None
    log_agent_event(
        event="agent.runtime.completed",
        organization_id=str(organization_id),
        user_id=str(user_id),
        run_id=str(run_id),
        mode=context.mode.value,
        steps_executed=context.steps_executed,
        tool_calls_executed=context.tool_calls_executed,
        total_tokens=context.total_tokens,
        total_cost_usd=str(context.total_cost_usd),
        confidence_score=confidence.get("score") if confidence is not None else None,
        confidence_category=confidence.get("category") if confidence is not None else None,
        not_found=outcome.not_found,
        blocked_document_instruction_signals=context.blocked_document_instruction_signals,
    )
    await rt._record_runtime_usage_event(
        session=session,
        organization_id=organization_id,
        user_id=user_id,
        run_id=run_id,
        request_id=request_id,
        context=context,
        status=AgentRunStatus.completed.value,
        confidence=confidence,
        not_found=outcome.not_found,
        error_code=None,
        runtime_ms=runtime_ms,
    )
    await rt._audit_completed(
        session=session,
        principal=principal,
        run_id=run_id,
        request_id=request_id,
        context=context,
        outcome=outcome,
    )
    return AgentRuntimeResult(
        run_id=str(run_id),
        status=AgentRunStatus.completed.value,
        steps_executed=context.steps_executed,
        tool_calls_executed=context.tool_calls_executed,
        total_tokens=context.total_tokens,
        total_cost_usd=context.total_cost_usd,
        outcome=outcome,
        error=None,
    )


async def cancel_run(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    run_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    context: _RuntimeContext,
    request_id: str | None,
    reason: str,
) -> AgentRuntimeResult:
    await rt._repository.update_agent_run(
        session,
        agent_run_id=run_id,
        organization_id=organization_id,
        status=AgentRunStatus.cancelled.value,
        cancelled_at=datetime.now(tz=UTC),
        observations={"cancellation_reason": reason, **_counters(context)},
        costs=_costs(context),
        total_cost_usd=float(context.total_cost_usd),
    )
    log_agent_event(
        event="agent.runtime.cancelled",
        organization_id=str(organization_id),
        run_id=str(run_id),
        mode=context.mode.value,
        reason=reason,
        steps_executed=context.steps_executed,
        tool_calls_executed=context.tool_calls_executed,
        total_tokens=context.total_tokens,
        total_cost_usd=str(context.total_cost_usd),
        blocked_document_instruction_signals=context.blocked_document_instruction_signals,
    )
    await rt._record_runtime_usage_event(
        session=session,
        organization_id=organization_id,
        user_id=user_id,
        run_id=run_id,
        request_id=request_id,
        context=context,
        status=AgentRunStatus.cancelled.value,
        confidence=None,
        not_found=None,
        error_code="cancelled",
        runtime_ms=None,
    )
    return AgentRuntimeResult(
        run_id=str(run_id),
        status=AgentRunStatus.cancelled.value,
        steps_executed=context.steps_executed,
        tool_calls_executed=context.tool_calls_executed,
        total_tokens=context.total_tokens,
        total_cost_usd=context.total_cost_usd,
        outcome=None,
        error=AgentRuntimeError(
            code="cancelled",
            message="Run cancelled",
            retryable=False,
            request_id=request_id,
            details={},
        ),
    )


async def fail_run(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    run_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    context: _RuntimeContext,
    request_id: str | None,
    code: str,
    message: str,
    details: dict[str, Any],
) -> AgentRuntimeResult:
    await rt._repository.update_agent_run(
        session,
        agent_run_id=run_id,
        organization_id=organization_id,
        status=AgentRunStatus.failed.value,
        completed_at=datetime.now(tz=UTC),
        error_message=message,
        error_details={"code": code, "details": details},
        costs=_costs(context),
        total_cost_usd=float(context.total_cost_usd),
        observations=_counters(context),
    )
    log_agent_event(
        event="agent.runtime.failed",
        organization_id=str(organization_id),
        user_id=str(user_id),
        run_id=str(run_id),
        mode=context.mode.value,
        error_code=code,
        steps_executed=context.steps_executed,
        tool_calls_executed=context.tool_calls_executed,
        total_tokens=context.total_tokens,
        total_cost_usd=str(context.total_cost_usd),
        blocked_document_instruction_signals=context.blocked_document_instruction_signals,
    )
    await rt._record_runtime_usage_event(
        session=session,
        organization_id=organization_id,
        user_id=user_id,
        run_id=run_id,
        request_id=request_id,
        context=context,
        status=AgentRunStatus.failed.value,
        confidence=None,
        not_found=None,
        error_code=code,
        runtime_ms=None,
    )
    await rt._audit_failed(
        session=session,
        organization_id=organization_id,
        run_id=run_id,
        request_id=request_id,
        code=code,
        message=message,
    )
    return AgentRuntimeResult(
        run_id=str(run_id),
        status=AgentRunStatus.failed.value,
        steps_executed=context.steps_executed,
        tool_calls_executed=context.tool_calls_executed,
        total_tokens=context.total_tokens,
        total_cost_usd=context.total_cost_usd,
        outcome=None,
        error=AgentRuntimeError(
            code=code,
            message=message,
            retryable=code in {"budget_exceeded", "tool_unavailable"},
            request_id=request_id,
            details=details,
        ),
    )


async def record_runtime_usage_event(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    organization_id: UUID,
    user_id: UUID,
    run_id: UUID,
    request_id: str | None,
    context: _RuntimeContext,
    status: str,
    confidence: dict[str, Any] | None,
    not_found: bool | None,
    error_code: str | None,
    runtime_ms: int | None,
) -> None:
    debug_usage: dict[str, Any] = {}
    if isinstance(context.latest_output, dict):
        debug = context.latest_output.get("debug")
        if isinstance(debug, dict):
            usage = debug.get("usage")
            if isinstance(usage, dict):
                debug_usage = usage
    embedding_prompt_tokens = safe_int(debug_usage.get("embedding_prompt_tokens"))
    llm_prompt_tokens = safe_int(debug_usage.get("llm_prompt_tokens"))
    llm_completion_tokens = safe_int(debug_usage.get("llm_completion_tokens"))
    input_tokens = embedding_prompt_tokens + llm_prompt_tokens
    output_tokens = llm_completion_tokens
    if input_tokens == 0 and output_tokens == 0 and context.total_tokens > 0:
        input_tokens = context.total_tokens

    metadata: dict[str, Any] = {
        "run_id": str(run_id),
        "status": status,
        "mode": context.mode.value,
        **_counters(context),
        "runtime_ms": runtime_ms,
        "request_id": request_id,
    }
    if confidence is not None:
        metadata["confidence_score"] = confidence.get("score")
        metadata["confidence_category"] = confidence.get("category")
    if not_found is not None:
        metadata["not_found"] = not_found
    if error_code is not None:
        metadata["error_code"] = error_code

    # Derive the actual provider/model from the last tool output debug block.
    detected_key, provider_type = _provider_metadata(context.latest_output)
    provider_key: str = detected_key or settings.openai_llm_model
    if provider_type is not None:
        metadata["provider_type"] = provider_type

    try:
        await rt._usage_repository.create_usage_event(
            session,
            organization_id=organization_id,
            user_id=user_id,
            event_type="agent.runtime",
            model_name=provider_key,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=context.total_cost_usd,
            metadata=metadata,
        )
    except Exception as exc:
        log_agent_event(
            event="agent.metrics.write_failed",
            organization_id=str(organization_id),
            user_id=str(user_id),
            run_id=str(run_id),
            metric_type="agent.runtime",
            error=exc.__class__.__name__,
        )


async def audit_started(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    run_id: UUID,
    request_id: str | None,
    mode: str,
    objective: str,
) -> None:
    await rt._audit_service.record(
        session,
        organization_id=rt._organization_uuid(principal),
        user_id=rt._user_uuid(principal),
        action="agent.runtime.started",
        resource_type="agent_run",
        resource_id=run_id,
        request_id=request_id,
        metadata={"mode": mode, "objective_preview": objective[:120]},
    )


async def audit_completed(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    run_id: UUID,
    request_id: str | None,
    context: _RuntimeContext,
    outcome: AgentRuntimeOutcome,
) -> None:
    await rt._audit_service.record(
        session,
        organization_id=rt._organization_uuid(principal),
        user_id=rt._user_uuid(principal),
        action="agent.runtime.completed",
        resource_type="agent_run",
        resource_id=run_id,
        request_id=request_id,
        metadata={
            "mode": context.mode.value,
            "steps_executed": context.steps_executed,
            "tool_calls_executed": context.tool_calls_executed,
            "not_found": outcome.not_found,
            "total_tokens": context.total_tokens,
            "total_cost_usd": str(context.total_cost_usd),
            "blocked_document_instruction_signals": context.blocked_document_instruction_signals,
        },
    )


async def audit_failed(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    organization_id: UUID,
    run_id: UUID,
    request_id: str | None,
    code: str,
    message: str,
) -> None:
    await rt._audit_service.record(
        session,
        organization_id=organization_id,
        user_id=None,
        action="agent.runtime.failed",
        resource_type="agent_run",
        resource_id=run_id,
        request_id=request_id,
        metadata={"code": code, "message": message},
    )
