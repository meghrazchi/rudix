"""Agent runtime facade: ``AgentRuntime.execute`` (plan-act-observe, R06-13 split).

The loop and its rules live in sibling modules, each re-exposed here under the names the
rest of the code base and the tests use:

- ``runtime_context``: run state, budget resolution and checks;
- ``runtime_plan``: the deterministic plan, argument resolution, observation;
- ``runtime_outcome``: complete, fail, cancel, the usage event, audits;
- ``runtime_steps``: the step loop (``execute_steps``);
- ``runtime_start``: preparation and the planning step, shared by both modes;
- ``runtime_resume``: worker resume after the last completed step.

``execute`` runs a request inline; ``execute_queued`` runs or resumes a stored run in a
worker that holds its lease (R06-13).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.agents.repositories import AgentRunRepository, AgentRunWorkerRepository
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
from app.domains.agents.services.run_stream import (
    NullRunEvents,
    RunEventSink,
    emit_result,
)
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
from app.domains.agents.services.runtime_resume import resume_steps
from app.domains.agents.services.runtime_start import StartArgs, prepare, start_run
from app.domains.agents.services.safety_guardrails import PromptInjectionGuard
from app.domains.agents.services.tool_executor import AgentToolExecutor
from app.domains.agents.services.tool_registry import ToolRegistry, build_default_tool_specs
from app.domains.chat.services.source_scope_service import (
    ResolvedSourceScope,
    SourceScopeService,
)
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.models.agent import AgentRun
from app.models.enums import AgentRunStatus

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
        self._worker_repository = AgentRunWorkerRepository()
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
        events_factory: Callable[[UUID], RunEventSink] | None = None,
    ) -> AgentRuntimeResult:
        """Run the whole plan now, in the caller's session (``AGENT_RUN_EXECUTION=inline``)."""
        organization_id = self._organization_uuid(principal)
        user_id = self._user_uuid(principal)
        started_at = datetime.now(tz=UTC)
        started_perf = perf_counter()
        prepared = await prepare(self, session=session, principal=principal, request=request)
        context = prepared.new_context()
        run = await self._repository.create_agent_run(
            session,
            organization_id=organization_id,
            user_id=user_id,
            status=AgentRunStatus.planning.value,
            surface="api",
            objective=request.objective,
            prompt_template_version_id=prepared.prompt_template_version_id,
            max_steps=prepared.budget.max_steps,
            max_parallel_tool_calls=settings.agent_max_parallel_tool_calls,
            budget=budget_payload(prepared.budget),
            observations=prepared.observations(request, context.mode.value),
            started_at=started_at,
            trace_request_id=request_id,
        )
        events = events_factory(run.id) if events_factory is not None else NullRunEvents()
        result = await start_run(
            self,
            StartArgs(
                session=session,
                principal=principal,
                run_id=run.id,
                request=request,
                prepared=prepared,
                context=context,
                started_at=started_at,
                started_perf=started_perf,
                request_id=request_id,
                cancel_signal=cancel_signal,
                events=events,
            ),
        )
        await emit_result(events, result)
        return result

    async def execute_queued(
        self,
        *,
        session: AsyncSession,
        principal: AuthenticatedPrincipal,
        run: AgentRun,
        request: AgentRuntimeRequest,
        request_id: str | None,
        checkpoint: Callable[[], Awaitable[None]],
        events: RunEventSink,
    ) -> AgentRuntimeResult:
        """Run or resume a stored run in a worker (``AGENT_RUN_EXECUTION=worker``).

        The caller holds the run's lease; ``checkpoint`` commits and renews it.
        """
        steps = await self._repository.list_agent_steps(
            session, agent_run_id=run.id, organization_id=run.organization_id
        )
        planning = next((step for step in steps if step.sequence == 0), None)
        if planning is not None:
            result = await resume_steps(
                self,
                session=session,
                principal=principal,
                run=run,
                request=request,
                planning=planning,
                steps=steps,
                request_id=request_id,
                events=events,
                checkpoint=checkpoint,
            )
        else:
            started_at = datetime.now(tz=UTC)
            started_perf = perf_counter()
            prepared = await prepare(self, session=session, principal=principal, request=request)
            context = prepared.new_context()
            run.prompt_template_version_id = prepared.prompt_template_version_id
            observations = dict(run.observations_json or {})
            observations.update(prepared.observations(request, context.mode.value))
            await self._repository.update_agent_run(
                session,
                agent_run_id=run.id,
                organization_id=run.organization_id,
                observations=observations,
                started_at=started_at,
            )
            result = await start_run(
                self,
                StartArgs(
                    session=session,
                    principal=principal,
                    run_id=run.id,
                    request=request,
                    prepared=prepared,
                    context=context,
                    started_at=started_at,
                    started_perf=started_perf,
                    request_id=request_id,
                    events=events,
                    checkpoint=checkpoint,
                ),
            )
        await emit_result(events, result)
        return result

    async def fail_queued(
        self,
        *,
        session: AsyncSession,
        run_id: UUID,
        organization_id: UUID,
        user_id: UUID | None,
        request: AgentRuntimeRequest,
        request_id: str | None,
        code: str,
        message: str,
        events: RunEventSink,
    ) -> AgentRuntimeResult:
        """Fail a stored run outside the loop (``principal_revoked``, unreadable request,
        an unexpected error); the ids are passed so a rolled-back session needs no reload."""
        context = _RuntimeContext(
            mode=select_mode(request),
            question=request.question or request.objective,
            selected_document_ids=list(request.document_ids),
        )
        result = await self._fail_run(
            session=session,
            run_id=run_id,
            organization_id=organization_id,
            user_id=user_id,
            context=context,
            request_id=request_id,
            code=code,
            message=message,
            details={},
        )
        await emit_result(events, result)
        return result

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
        current = await self._worker_repository.read_status(
            session, run_id=run_id, organization_id=organization_id
        )
        if current is None:
            return True
        status, cancelled_at = current
        return status == AgentRunStatus.cancelled.value or cancelled_at is not None

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
