"""Preparation and start of an agent run, shared by inline and worker execution (R06-13).

``prepare`` registers external MCP tools, resolves the agent planning prompt template, and
resolves the request's source scope with the principal's current roles. ``start_run``
writes the planning step (sequence 0), runs the request guard, moves the run to
``running``, and hands over to the step loop. Inline mode runs both inside
``POST /agent/runs``; worker mode runs them in ``agents.run.execute``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_agent_event
from app.domains.agents.schemas import (
    AgentBudgetConfig,
    AgentRuntimeRequest,
    AgentRuntimeResult,
)
from app.domains.agents.services.run_stream import NullRunEvents, RunEventSink
from app.domains.agents.services.runtime_context import _RuntimeContext, select_mode
from app.domains.agents.services.runtime_steps import StepLoop, execute_steps
from app.domains.chat.services.source_scope_service import ResolvedSourceScope
from app.domains.prompt_templates.services.rendering import PromptTemplateValidationError
from app.models.enums import AgentRunStatus, AgentStepStatus, PromptTemplateKey

if TYPE_CHECKING:
    from app.domains.agents.services.runtime import AgentRuntime


@dataclass
class Prepared:
    budget: AgentBudgetConfig
    effective_request: AgentRuntimeRequest
    prompt_template_version_id: UUID | None
    prompt_template_metadata: dict[str, object] | None
    external_mcp: dict[str, Any]
    source_scope_result: ResolvedSourceScope | None

    def new_context(self) -> _RuntimeContext:
        request = self.effective_request
        return _RuntimeContext(
            mode=select_mode(request),
            question=request.question or request.objective,
            selected_document_ids=list(request.document_ids),
        )

    def observations(self, request: AgentRuntimeRequest, mode: str) -> dict[str, Any]:
        return {
            "request_metadata": request.metadata,
            "mode": mode,
            "prompt_template": self.prompt_template_metadata,
            "external_mcp": self.external_mcp,
        }


async def prepare(
    rt: AgentRuntime,
    *,
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    request: AgentRuntimeRequest,
) -> Prepared:
    organization_id = rt._organization_uuid(principal)
    user_id = rt._user_uuid(principal)
    summary = await rt._external_mcp_tool_manager.ensure_registered(registry=rt._registry)
    prompt_template_metadata: dict[str, object] | None = None
    prompt_template_version_id: UUID | None = None
    try:
        prompt_version = await rt._prompt_template_service.resolve_active_version(
            session,
            organization_id=organization_id,
            template_key=PromptTemplateKey.agent_planning.value,
        )
    except PromptTemplateValidationError:
        prompt_version = None
    if prompt_version is not None:
        prompt_template_version_id = prompt_version.id
        prompt_template_metadata = {
            "key": PromptTemplateKey.agent_planning.value,
            "version_number": prompt_version.version_number,
            "version_id": str(prompt_version.id),
        }
    source_scope_result = await rt._resolve_request_source_scope(
        session=session,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=list(principal.roles or []),
        request=request,
    )
    effective_request = request
    if source_scope_result is not None and source_scope_result.document_ids:
        effective_request = request.model_copy(
            update={
                "document_ids": [
                    str(document_id) for document_id in source_scope_result.document_ids
                ],
            }
        )
    return Prepared(
        budget=rt._resolve_budget(request.budget),
        effective_request=effective_request,
        prompt_template_version_id=prompt_template_version_id,
        prompt_template_metadata=prompt_template_metadata,
        external_mcp={
            "enabled": summary.enabled,
            "configured_servers": summary.configured_servers,
            "discovered_servers": summary.discovered_servers,
            "registered_tools": list(summary.registered_tools),
            "warning_count": len(summary.warnings),
        },
        source_scope_result=source_scope_result,
    )


@dataclass
class StartArgs:
    session: AsyncSession
    principal: AuthenticatedPrincipal
    run_id: UUID
    request: AgentRuntimeRequest
    prepared: Prepared
    context: _RuntimeContext
    started_at: datetime
    started_perf: float
    request_id: str | None
    cancel_signal: Callable[[], bool] | None = None
    events: RunEventSink | None = None
    checkpoint: Callable[[], Awaitable[None]] | None = None


async def start_run(rt: AgentRuntime, args: StartArgs) -> AgentRuntimeResult:
    session = args.session
    organization_id = rt._organization_uuid(args.principal)
    user_id = rt._user_uuid(args.principal)
    context = args.context
    prepared = args.prepared
    request = args.request
    effective_request = prepared.effective_request
    budget = prepared.budget
    scope = prepared.source_scope_result

    async def fail(code: str, message: str, details: dict[str, Any]) -> AgentRuntimeResult:
        return await rt._fail_run(
            session=session,
            run_id=args.run_id,
            organization_id=organization_id,
            user_id=user_id,
            context=context,
            request_id=args.request_id,
            code=code,
            message=message,
            details=details,
        )

    if scope is not None and scope.document_ids == []:
        return await fail(
            "validation_failed",
            "No accessible documents matched the selected sources.",
            {
                "source_scope_mode": request.source_scope.mode
                if request.source_scope is not None
                else None,
                "source_scope_label": scope.label,
            },
        )
    plan = rt._build_plan(request=effective_request)
    log_agent_event(
        event="agent.runtime.started",
        organization_id=str(organization_id),
        user_id=str(user_id),
        run_id=str(args.run_id),
        mode=context.mode.value,
        max_steps=budget.max_steps,
        max_runtime_ms=budget.max_runtime_ms,
        max_tool_calls=budget.max_tool_calls,
    )
    await rt._audit_started(
        session=session,
        principal=args.principal,
        run_id=args.run_id,
        request_id=args.request_id,
        mode=context.mode.value,
        objective=request.objective,
    )

    if settings.agent_prompt_injection_guard_enabled:
        request_injection = rt._safety_guard.evaluate_request(
            objective=effective_request.objective,
            question=effective_request.question,
            document_query=effective_request.document_query,
        )
        if request_injection.blocked:
            return await fail(
                "prompt_injection_blocked",
                "Potential prompt-injection content was detected. Revise and retry.",
                {"signals": request_injection.reasons},
            )

    await rt._repository.create_agent_step(
        session,
        agent_run_id=args.run_id,
        organization_id=organization_id,
        user_id=user_id,
        sequence=0,
        step_name="plan",
        status=AgentStepStatus.completed.value,
        inputs={"objective": request.objective},
        outputs={"selections": [item.model_dump() for item in plan]},
        metrics={"selection_count": len(plan)},
        # Worker mode: a resumed task restores the documents the plan runs on from here.
        observation={"selected_document_ids": context.selected_document_ids}
        if args.checkpoint is not None
        else None,
        started_at=args.started_at,
        completed_at=datetime.now(tz=UTC),
        duration_ms=int((perf_counter() - args.started_perf) * 1000),
    )
    await rt._repository.update_agent_run(
        session,
        agent_run_id=args.run_id,
        organization_id=organization_id,
        status=AgentRunStatus.running.value,
    )
    loop = StepLoop(
        session=session,
        principal=args.principal,
        run_id=args.run_id,
        organization_id=organization_id,
        user_id=user_id,
        request=request,
        plan=plan,
        budget=budget,
        context=context,
        request_id=args.request_id,
        started_perf=args.started_perf,
        cancel_signal=args.cancel_signal,
        events=args.events or NullRunEvents(),
        checkpoint=args.checkpoint,
    )
    await loop.save()
    return await execute_steps(rt, loop, start_sequence=1)
