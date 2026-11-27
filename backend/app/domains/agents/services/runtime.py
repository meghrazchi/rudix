"""Agent runtime facade: ``AgentRuntime.execute`` (plan-act-observe, R06-13 split).

The loop and its rules live in sibling modules, each re-exposed here under the names the
rest of the code base and the tests use:

- ``runtime_context``: run state, budget resolution and checks;
- ``runtime_plan``: the deterministic plan, argument resolution, observation;
- ``runtime_outcome``: complete, fail, cancel, the usage event, audits;
- ``runtime_steps``: the step loop (``execute_steps``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_agent_event
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.agents.repositories import AgentRunRepository
from app.domains.agents.schemas import (
    AgentRuntimeOutcome,
    AgentRuntimeRequest,
    AgentRuntimeResult,
    PlannedToolSelection,
)
from app.domains.agents.services.document_intelligence_tools import (
    register_document_intelligence_handlers,
)
from app.domains.agents.services.external_mcp import ExternalMCPToolManager
from app.domains.agents.services.runtime_context import (
    _RuntimeContext,
    budget_payload,
    check_budget_after_step,
    check_budget_before_step,
    extract_usage,
    resolve_budget,
    safe_int,
    select_mode,
)
from app.domains.agents.services.runtime_outcome import (
    audit_completed,
    audit_failed,
    audit_started,
    build_outcome,
    cancel_run,
    complete_run,
    fail_run,
    record_runtime_usage_event,
)
from app.domains.agents.services.runtime_plan import (
    build_plan,
    is_uuid_string,
    observe_after_step,
    parse_document_ids,
    resolve_selection_arguments,
)
from app.domains.agents.services.runtime_steps import StepLoop, execute_steps
from app.domains.agents.services.safety_guardrails import PromptInjectionGuard
from app.domains.agents.services.tool_executor import AgentToolExecutor
from app.domains.agents.services.tool_registry import ToolRegistry, build_default_tool_specs
from app.domains.chat.services.source_scope_service import (
    ResolvedSourceScope,
    SourceScopeService,
)
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.domains.prompt_templates.services.rendering import PromptTemplateValidationError
from app.models.enums import AgentRunStatus, AgentStepStatus, PromptTemplateKey

__all__ = ["AgentRuntime", "_RuntimeContext"]


class AgentRuntime:
    """Plan-act-observe runtime loop for internal agentic execution."""

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        repository: AgentRunRepository | None = None,
        executor: AgentToolExecutor | None = None,
        audit_service: AuditLogService | None = None,
        safety_guard: PromptInjectionGuard | None = None,
        usage_repository: UsageRepository | None = None,
        external_mcp_tool_manager: ExternalMCPToolManager | None = None,
        source_scope_service: SourceScopeService | None = None,
    ) -> None:
        resolved_registry = registry or ToolRegistry(specs=build_default_tool_specs())
        if registry is None:
            register_document_intelligence_handlers(registry=resolved_registry)

        self._registry = resolved_registry
        self._repository = repository or AgentRunRepository()
        self._audit_service = audit_service or AuditLogService()
        self._safety_guard = safety_guard or PromptInjectionGuard()
        self._usage_repository = usage_repository or UsageRepository()
        self._external_mcp_tool_manager = external_mcp_tool_manager or ExternalMCPToolManager()
        self._source_scope_service = source_scope_service or SourceScopeService()
        self._prompt_template_service = PromptTemplateService()
        self._executor = executor or AgentToolExecutor(
            registry=self._registry,
            repository=self._repository,
            audit_service=self._audit_service,
        )

    async def execute(
        self,
        *,
        session: AsyncSession,
        principal: AuthenticatedPrincipal,
        request: AgentRuntimeRequest,
        request_id: str | None = None,
        cancel_signal: Callable[[], bool] | None = None,
    ) -> AgentRuntimeResult:
        organization_id = self._organization_uuid(principal)
        user_id = self._user_uuid(principal)
        started_at = datetime.now(tz=UTC)
        started_perf = perf_counter()
        budget = self._resolve_budget(request.budget)
        effective_request = request
        external_mcp_summary = await self._external_mcp_tool_manager.ensure_registered(
            registry=self._registry
        )
        prompt_template_metadata: dict[str, object] | None = None
        prompt_template_version_id: UUID | None = None
        try:
            prompt_version = await self._prompt_template_service.resolve_active_version(
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
        source_scope_result = await self._resolve_request_source_scope(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            user_roles=list(principal.roles or []),
            request=request,
        )
        source_scope_mode = request.source_scope.mode if request.source_scope is not None else None
        if source_scope_result is not None:
            if source_scope_result.document_ids:
                effective_request = request.model_copy(
                    update={
                        "document_ids": [
                            str(document_id) for document_id in source_scope_result.document_ids
                        ],
                    }
                )
        context = _RuntimeContext(
            mode=self._select_mode(effective_request),
            question=effective_request.question or effective_request.objective,
            selected_document_ids=list(effective_request.document_ids),
        )
        run = await self._repository.create_agent_run(
            session,
            organization_id=organization_id,
            user_id=user_id,
            status=AgentRunStatus.planning.value,
            surface="api",
            objective=request.objective,
            prompt_template_version_id=prompt_template_version_id,
            max_steps=budget.max_steps,
            max_parallel_tool_calls=settings.agent_max_parallel_tool_calls,
            budget=budget_payload(budget),
            observations={
                "request_metadata": request.metadata,
                "mode": context.mode.value,
                "prompt_template": prompt_template_metadata,
                "external_mcp": {
                    "enabled": external_mcp_summary.enabled,
                    "configured_servers": external_mcp_summary.configured_servers,
                    "discovered_servers": external_mcp_summary.discovered_servers,
                    "registered_tools": list(external_mcp_summary.registered_tools),
                    "warning_count": len(external_mcp_summary.warnings),
                },
            },
            started_at=started_at,
            trace_request_id=request_id,
        )
        if source_scope_result is not None and source_scope_result.document_ids == []:
            return await self._fail_run(
                session=session,
                run_id=run.id,
                organization_id=organization_id,
                user_id=user_id,
                context=context,
                request_id=request_id,
                code="validation_failed",
                message="No accessible documents matched the selected sources.",
                details={
                    "source_scope_mode": source_scope_mode,
                    "source_scope_label": source_scope_result.label,
                },
            )
        plan = self._build_plan(request=effective_request)
        log_agent_event(
            event="agent.runtime.started",
            organization_id=str(organization_id),
            user_id=str(user_id),
            run_id=str(run.id),
            mode=context.mode.value,
            max_steps=budget.max_steps,
            max_runtime_ms=budget.max_runtime_ms,
            max_tool_calls=budget.max_tool_calls,
        )
        await self._audit_started(
            session=session,
            principal=principal,
            run_id=run.id,
            request_id=request_id,
            mode=context.mode.value,
            objective=request.objective,
        )

        if settings.agent_prompt_injection_guard_enabled:
            request_injection = self._safety_guard.evaluate_request(
                objective=effective_request.objective,
                question=effective_request.question,
                document_query=effective_request.document_query,
            )
            if request_injection.blocked:
                return await self._fail_run(
                    session=session,
                    run_id=run.id,
                    organization_id=organization_id,
                    user_id=user_id,
                    context=context,
                    request_id=request_id,
                    code="prompt_injection_blocked",
                    message="Potential prompt-injection content was detected. Revise and retry.",
                    details={"signals": request_injection.reasons},
                )

        planning_step = await self._repository.create_agent_step(
            session,
            agent_run_id=run.id,
            organization_id=organization_id,
            user_id=user_id,
            sequence=0,
            step_name="plan",
            status=AgentStepStatus.completed.value,
            inputs={"objective": request.objective},
            outputs={"selections": [item.model_dump() for item in plan]},
            metrics={"selection_count": len(plan)},
            started_at=started_at,
            completed_at=datetime.now(tz=UTC),
            duration_ms=int((perf_counter() - started_perf) * 1000),
        )
        del planning_step
        await self._repository.update_agent_run(
            session,
            agent_run_id=run.id,
            organization_id=organization_id,
            status=AgentRunStatus.running.value,
        )

        loop = StepLoop(
            session=session,
            principal=principal,
            run_id=run.id,
            organization_id=organization_id,
            user_id=user_id,
            request=request,
            plan=plan,
            budget=budget,
            context=context,
            request_id=request_id,
            started_perf=started_perf,
            cancel_signal=cancel_signal,
        )
        return await execute_steps(self, loop, start_sequence=1)

    # Budget, plan, and observation rules (runtime_context, runtime_plan).
    _resolve_budget = staticmethod(resolve_budget)
    _select_mode = staticmethod(select_mode)
    _check_budget_before_step = staticmethod(check_budget_before_step)
    _check_budget_after_step = staticmethod(check_budget_after_step)
    _extract_usage = staticmethod(extract_usage)
    _safe_int = staticmethod(safe_int)
    _parse_document_ids = staticmethod(parse_document_ids)
    _is_uuid_string = staticmethod(is_uuid_string)

    def _build_plan(self, *, request: AgentRuntimeRequest) -> list[PlannedToolSelection]:
        return build_plan(request=request)

    def preview_plan(self, *, request: AgentRuntimeRequest) -> list[PlannedToolSelection]:
        """Expose the deterministic tool plan without executing it."""
        return build_plan(request=request)

    def _resolve_selection_arguments(
        self, *, selection: PlannedToolSelection, context: _RuntimeContext
    ) -> dict[str, Any]:
        return resolve_selection_arguments(selection=selection, context=context)

    def _observe_after_step(
        self,
        *,
        selection: PlannedToolSelection,
        output: dict[str, Any],
        context: _RuntimeContext,
    ) -> None:
        observe_after_step(
            selection=selection, output=output, context=context, safety_guard=self._safety_guard
        )

    def _build_outcome(self, *, context: _RuntimeContext) -> AgentRuntimeOutcome:
        return build_outcome(context=context)

    async def _resolve_request_source_scope(
        self,
        *,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        request: AgentRuntimeRequest,
    ) -> ResolvedSourceScope | None:
        if request.source_scope is None:
            return None
        explicit_document_ids = parse_document_ids(request.document_ids)
        return await self._source_scope_service.resolve_document_ids(
            session,
            organization_id=organization_id,
            user_id=user_id,
            user_roles=user_roles,
            source_scope=request.source_scope,
            explicit_document_ids=explicit_document_ids,
        )

    async def _is_cancelled_run(
        self,
        *,
        session: AsyncSession,
        run_id: UUID,
        organization_id: UUID,
    ) -> bool:
        run = await self._repository.get_agent_run(
            session,
            agent_run_id=run_id,
            organization_id=organization_id,
        )
        if run is None:
            return True
        return run.status == AgentRunStatus.cancelled.value or run.cancelled_at is not None

    # Terminal transitions, usage event, and audits (runtime_outcome).
    async def _complete_run(self, **kwargs: Any) -> AgentRuntimeResult:
        return await complete_run(self, **kwargs)

    async def _cancel_run(self, **kwargs: Any) -> AgentRuntimeResult:
        return await cancel_run(self, **kwargs)

    async def _fail_run(self, **kwargs: Any) -> AgentRuntimeResult:
        return await fail_run(self, **kwargs)

    async def _record_runtime_usage_event(self, **kwargs: Any) -> None:
        await record_runtime_usage_event(self, **kwargs)

    async def _audit_started(self, **kwargs: Any) -> None:
        await audit_started(self, **kwargs)

    async def _audit_completed(self, **kwargs: Any) -> None:
        await audit_completed(self, **kwargs)

    async def _audit_failed(self, **kwargs: Any) -> None:
        await audit_failed(self, **kwargs)

    @staticmethod
    def _organization_uuid(principal: AuthenticatedPrincipal) -> UUID:
        if principal.organization_id is None:
            raise AuthorizationError("No active organization context for principal")
        try:
            return UUID(principal.organization_id)
        except ValueError as exc:
            raise AuthorizationError("Principal organization context is invalid") from exc

    @staticmethod
    def _user_uuid(principal: AuthenticatedPrincipal) -> UUID:
        try:
            return UUID(principal.user_id)
        except ValueError as exc:
            raise AuthorizationError("Principal user context is invalid") from exc
