from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.agents.repositories import AgentRunRepository
from app.domains.agents.schemas import (
    AgentBudgetConfig,
    AgentRuntimeError,
    AgentRuntimeMode,
    AgentRuntimeOutcome,
    AgentRuntimeRequest,
    AgentRuntimeResult,
    PlannedToolSelection,
    ToolCall,
    ToolEffectPolicy,
)
from app.domains.agents.services.document_intelligence_tools import (
    register_document_intelligence_handlers,
)
from app.domains.agents.services.tool_executor import AgentToolExecutor
from app.domains.agents.services.tool_registry import ToolRegistry, build_default_tool_specs
from app.models.enums import AgentRunStatus, AgentStepStatus

_SELECTED_DOCUMENT_IDS = "__selected_document_ids__"
_SELECTED_DOCUMENT_ID = "__selected_document_id__"


@dataclass
class _RuntimeContext:
    mode: AgentRuntimeMode
    question: str
    selected_document_ids: list[str]
    latest_output: dict[str, Any] | None = None
    steps_executed: int = 0
    tool_calls_executed: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")


class AgentRuntime:
    """Plan-act-observe runtime loop for internal agentic execution."""

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        repository: AgentRunRepository | None = None,
        executor: AgentToolExecutor | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        resolved_registry = registry or ToolRegistry(specs=build_default_tool_specs())
        if registry is None:
            register_document_intelligence_handlers(registry=resolved_registry)

        self._registry = resolved_registry
        self._repository = repository or AgentRunRepository()
        self._audit_service = audit_service or AuditLogService()
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
        plan = self._build_plan(request=request)
        context = _RuntimeContext(
            mode=self._select_mode(request),
            question=request.question or request.objective,
            selected_document_ids=list(request.document_ids),
        )

        run = await self._repository.create_agent_run(
            session,
            organization_id=organization_id,
            user_id=user_id,
            status=AgentRunStatus.planning.value,
            surface="api",
            objective=request.objective,
            max_steps=budget.max_steps,
            max_parallel_tool_calls=settings.agent_max_parallel_tool_calls,
            budget={
                "max_steps": budget.max_steps,
                "max_runtime_ms": budget.max_runtime_ms,
                "max_tool_calls": budget.max_tool_calls,
                "max_total_tokens": budget.max_total_tokens,
                "max_total_cost_usd": str(budget.max_total_cost_usd) if budget.max_total_cost_usd is not None else None,
            },
            observations={
                "request_metadata": request.metadata,
                "mode": context.mode.value,
            },
            started_at=started_at,
            trace_request_id=request_id,
        )
        await self._audit_started(
            session=session,
            principal=principal,
            run_id=run.id,
            request_id=request_id,
            mode=context.mode.value,
            objective=request.objective,
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

        for sequence, selection in enumerate(plan, start=1):
            elapsed_ms = int((perf_counter() - started_perf) * 1000)
            budget_error = self._check_budget_before_step(
                budget=budget,
                context=context,
                elapsed_ms=elapsed_ms,
            )
            if budget_error is not None:
                return await self._fail_run(
                    session=session,
                    run_id=run.id,
                    organization_id=organization_id,
                    context=context,
                    request_id=request_id,
                    code="budget_exceeded",
                    message=budget_error,
                    details={"elapsed_ms": elapsed_ms},
                )

            if cancel_signal is not None and cancel_signal():
                return await self._cancel_run(
                    session=session,
                    run_id=run.id,
                    organization_id=organization_id,
                    context=context,
                    request_id=request_id,
                    reason="cancelled_by_signal",
                )

            if await self._is_cancelled_run(
                session=session,
                run_id=run.id,
                organization_id=organization_id,
            ):
                return await self._cancel_run(
                    session=session,
                    run_id=run.id,
                    organization_id=organization_id,
                    context=context,
                    request_id=request_id,
                    reason="cancelled_in_persistence",
                )

            try:
                arguments = self._resolve_selection_arguments(
                    selection=selection,
                    context=context,
                )
            except ValueError as exc:
                return await self._fail_run(
                    session=session,
                    run_id=run.id,
                    organization_id=organization_id,
                    context=context,
                    request_id=request_id,
                    code="validation_failed",
                    message=str(exc),
                    details={},
                )
            step_started_dt = datetime.now(tz=UTC)
            step_started_perf = perf_counter()
            step = await self._repository.create_agent_step(
                session,
                agent_run_id=run.id,
                organization_id=organization_id,
                user_id=user_id,
                sequence=sequence,
                step_name=selection.step_name,
                status=AgentStepStatus.running.value,
                inputs={
                    "tool_name": selection.tool_name,
                    "arguments": arguments,
                    "rationale": selection.rationale,
                },
                started_at=step_started_dt,
            )
            spec = self._registry.get_spec(selection.tool_name)
            idempotency_key: str | None = None
            if spec is not None and spec.effect_policy is ToolEffectPolicy.side_effect:
                idempotency_key = f"{run.id}:{sequence}:{selection.tool_name}"
            tool_call = ToolCall(
                run_id=str(run.id),
                tool_name=selection.tool_name,
                organization_id=str(organization_id),
                user_id=str(user_id),
                arguments=arguments,
                idempotency_key=idempotency_key,
            )
            tool_result = await self._executor.execute(
                session=session,
                call=tool_call,
                principal=principal,
                request_id=request_id,
            )
            context.tool_calls_executed += 1

            if not tool_result.success:
                await self._repository.update_agent_step(
                    session,
                    agent_step_id=step.id,
                    organization_id=organization_id,
                    status=AgentStepStatus.failed.value,
                    outputs={},
                    metrics={"latency_ms": tool_result.latency_ms or 0},
                    error_message=tool_result.error.safe_message if tool_result.error is not None else None,
                    error_details=tool_result.error.model_dump() if tool_result.error is not None else {},
                    completed_at=datetime.now(tz=UTC),
                    duration_ms=int((perf_counter() - step_started_perf) * 1000),
                )
                return await self._fail_run(
                    session=session,
                    run_id=run.id,
                    organization_id=organization_id,
                    context=context,
                    request_id=request_id,
                    code=tool_result.error.code.value if tool_result.error is not None else "internal_error",
                    message=tool_result.error.safe_message if tool_result.error is not None else "Tool execution failed",
                    details=tool_result.error.details if tool_result.error is not None else {},
                )

            output = tool_result.output or {}
            context.latest_output = output
            context.steps_executed += 1
            self._observe_after_step(
                selection=selection,
                output=output,
                context=context,
            )
            usage = self._extract_usage(output)
            context.total_tokens += usage["total_tokens"]
            context.total_cost_usd += usage["total_cost_usd"]

            step_budget_error = self._check_budget_after_step(budget=budget, context=context)
            if step_budget_error is not None:
                await self._repository.update_agent_step(
                    session,
                    agent_step_id=step.id,
                    organization_id=organization_id,
                    status=AgentStepStatus.failed.value,
                    outputs=output,
                    metrics={
                        "latency_ms": tool_result.latency_ms or 0,
                        "total_tokens": context.total_tokens,
                        "total_cost_usd": str(context.total_cost_usd),
                    },
                    error_message=step_budget_error,
                    error_details={"code": "budget_exceeded"},
                    completed_at=datetime.now(tz=UTC),
                    duration_ms=int((perf_counter() - step_started_perf) * 1000),
                )
                return await self._fail_run(
                    session=session,
                    run_id=run.id,
                    organization_id=organization_id,
                    context=context,
                    request_id=request_id,
                    code="budget_exceeded",
                    message=step_budget_error,
                    details={},
                )

            await self._repository.update_agent_step(
                session,
                agent_step_id=step.id,
                organization_id=organization_id,
                status=AgentStepStatus.completed.value,
                outputs=output,
                metrics={
                    "latency_ms": tool_result.latency_ms or 0,
                    "total_tokens": context.total_tokens,
                    "total_cost_usd": str(context.total_cost_usd),
                },
                completed_at=datetime.now(tz=UTC),
                duration_ms=int((perf_counter() - step_started_perf) * 1000),
            )

        outcome = self._build_outcome(context=context)
        await self._repository.update_agent_run(
            session,
            agent_run_id=run.id,
            organization_id=organization_id,
            status=AgentRunStatus.completed.value,
            completed_at=datetime.now(tz=UTC),
            outcome=outcome.model_dump(),
            costs={
                "total_tokens": context.total_tokens,
                "total_cost_usd": str(context.total_cost_usd),
            },
            total_cost_usd=float(context.total_cost_usd),
            observations={
                "selected_document_ids": context.selected_document_ids,
                "steps_executed": context.steps_executed,
                "tool_calls_executed": context.tool_calls_executed,
            },
        )
        await self._audit_completed(
            session=session,
            principal=principal,
            run_id=run.id,
            request_id=request_id,
            context=context,
            outcome=outcome,
        )
        return AgentRuntimeResult(
            run_id=str(run.id),
            status=AgentRunStatus.completed.value,
            steps_executed=context.steps_executed,
            tool_calls_executed=context.tool_calls_executed,
            total_tokens=context.total_tokens,
            total_cost_usd=context.total_cost_usd,
            outcome=outcome,
            error=None,
        )

    def _resolve_budget(self, requested_budget: AgentBudgetConfig | None) -> AgentBudgetConfig:
        defaults = AgentBudgetConfig(
            max_steps=settings.agent_max_steps,
            max_runtime_ms=max(settings.agent_max_steps * settings.agent_tool_timeout_ms, 5_000),
            max_tool_calls=settings.agent_tool_max_calls_per_run,
            max_total_tokens=None,
            max_total_cost_usd=None,
        )
        if requested_budget is None:
            return defaults
        return AgentBudgetConfig(
            max_steps=min(requested_budget.max_steps, defaults.max_steps),
            max_runtime_ms=min(requested_budget.max_runtime_ms, defaults.max_runtime_ms),
            max_tool_calls=min(requested_budget.max_tool_calls, defaults.max_tool_calls),
            max_total_tokens=requested_budget.max_total_tokens,
            max_total_cost_usd=requested_budget.max_total_cost_usd,
        )

    def _select_mode(self, request: AgentRuntimeRequest) -> AgentRuntimeMode:
        if request.mode is not AgentRuntimeMode.auto:
            return request.mode
        objective = request.objective.lower()
        if len(request.document_ids) > 1 or "compare" in objective:
            return AgentRuntimeMode.compare
        if "summary" in objective or "summarize" in objective:
            return AgentRuntimeMode.summarize
        return AgentRuntimeMode.answer

    def _build_plan(self, *, request: AgentRuntimeRequest) -> list[PlannedToolSelection]:
        mode = self._select_mode(request)
        question = request.question or request.objective
        top_k = request.top_k or settings.retrieval_final_top_k
        rerank = request.rerank if request.rerank is not None else True

        selections: list[PlannedToolSelection] = []
        if not request.document_ids:
            selections.append(
                PlannedToolSelection(
                    step_name="discover_documents",
                    tool_name="search_documents",
                    arguments={
                        "query": request.document_query or question[:120],
                        "status": "indexed",
                        "sort_by": "updated_at",
                        "sort_order": "desc",
                        "limit": 25,
                        "offset": 0,
                    },
                    rationale="Find indexed accessible documents to ground the answer.",
                )
            )

        if mode is AgentRuntimeMode.answer:
            selections.append(
                PlannedToolSelection(
                    step_name="grounded_answer",
                    tool_name="answer_from_context",
                    arguments={
                        "question": question,
                        "document_ids": _SELECTED_DOCUMENT_IDS,
                        "top_k": top_k,
                        "rerank": rerank,
                    },
                    rationale="Answer using retrieved document context with citations and confidence.",
                )
            )
        elif mode is AgentRuntimeMode.summarize:
            selections.append(
                PlannedToolSelection(
                    step_name="document_summary",
                    tool_name="summarize_document",
                    arguments={
                        "document_id": _SELECTED_DOCUMENT_ID,
                        "top_k": top_k,
                        "rerank": rerank,
                    },
                    rationale="Create a grounded summary for one selected document.",
                )
            )
        else:
            selections.append(
                PlannedToolSelection(
                    step_name="document_comparison",
                    tool_name="compare_documents",
                    arguments={
                        "question": question,
                        "document_ids": _SELECTED_DOCUMENT_IDS,
                        "top_k": top_k,
                        "rerank": rerank,
                    },
                    rationale="Compare grounded evidence across selected documents.",
                )
            )

        return selections

    def _resolve_selection_arguments(
        self,
        *,
        selection: PlannedToolSelection,
        context: _RuntimeContext,
    ) -> dict[str, Any]:
        arguments = dict(selection.arguments)
        if arguments.get("document_ids") == _SELECTED_DOCUMENT_IDS:
            if not context.selected_document_ids:
                raise ValueError("No accessible indexed documents were found for this request")
            if selection.tool_name == "compare_documents" and len(context.selected_document_ids) < 2:
                raise ValueError("At least two documents are required for compare mode")
            arguments["document_ids"] = context.selected_document_ids
        if arguments.get("document_id") == _SELECTED_DOCUMENT_ID:
            if not context.selected_document_ids:
                raise ValueError("No accessible indexed documents were found for this request")
            arguments["document_id"] = context.selected_document_ids[0]
        return arguments

    def _observe_after_step(
        self,
        *,
        selection: PlannedToolSelection,
        output: dict[str, Any],
        context: _RuntimeContext,
    ) -> None:
        if selection.tool_name != "search_documents":
            return
        items = output.get("items")
        if not isinstance(items, list):
            return
        document_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            document_id = item.get("document_id")
            status = item.get("status")
            if isinstance(document_id, str) and document_id.strip() and status == "indexed":
                document_ids.append(document_id)
        # Keep selection bounded for downstream cost/runtime.
        context.selected_document_ids = document_ids[:10]

    def _extract_usage(self, output: dict[str, Any]) -> dict[str, Any]:
        debug = output.get("debug")
        if not isinstance(debug, dict):
            return {"total_tokens": 0, "total_cost_usd": Decimal("0")}
        usage = debug.get("usage")
        if not isinstance(usage, dict):
            return {"total_tokens": 0, "total_cost_usd": Decimal("0")}
        raw_tokens = usage.get("total_tokens", 0)
        raw_cost = usage.get("total_cost_usd", "0")
        try:
            total_tokens = int(raw_tokens)
        except (TypeError, ValueError):
            total_tokens = 0
        try:
            total_cost_usd = Decimal(str(raw_cost))
        except Exception:
            total_cost_usd = Decimal("0")
        return {
            "total_tokens": max(total_tokens, 0),
            "total_cost_usd": max(total_cost_usd, Decimal("0")),
        }

    def _check_budget_before_step(
        self,
        *,
        budget: AgentBudgetConfig,
        context: _RuntimeContext,
        elapsed_ms: int,
    ) -> str | None:
        if context.steps_executed >= budget.max_steps:
            return "Step budget exceeded"
        if context.tool_calls_executed >= budget.max_tool_calls:
            return "Tool-call budget exceeded"
        if elapsed_ms > budget.max_runtime_ms:
            return "Runtime budget exceeded"
        return None

    def _check_budget_after_step(self, *, budget: AgentBudgetConfig, context: _RuntimeContext) -> str | None:
        if budget.max_total_tokens is not None and context.total_tokens > budget.max_total_tokens:
            return "Token budget exceeded"
        if budget.max_total_cost_usd is not None and context.total_cost_usd > budget.max_total_cost_usd:
            return "Cost budget exceeded"
        return None

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

    def _build_outcome(self, *, context: _RuntimeContext) -> AgentRuntimeOutcome:
        output = context.latest_output or {}
        if context.mode is AgentRuntimeMode.answer:
            answer = str(output.get("response", ""))
            return AgentRuntimeOutcome(
                answer=answer,
                citations=output.get("citations", []) if isinstance(output.get("citations"), list) else [],
                confidence=output.get("confidence", {}) if isinstance(output.get("confidence"), dict) else {},
                not_found=bool(output.get("not_found", False)),
                mode=context.mode,
            )
        if context.mode is AgentRuntimeMode.summarize:
            return AgentRuntimeOutcome(
                answer=str(output.get("summary", "")),
                citations=output.get("citations", []) if isinstance(output.get("citations"), list) else [],
                confidence=output.get("confidence", {}) if isinstance(output.get("confidence"), dict) else {},
                not_found=bool(output.get("not_found", False)),
                mode=context.mode,
            )
        return AgentRuntimeOutcome(
            answer=str(output.get("comparison", "")),
            citations=output.get("citations", []) if isinstance(output.get("citations"), list) else [],
            confidence=output.get("confidence", {}) if isinstance(output.get("confidence"), dict) else {},
            not_found=bool(output.get("not_found", False)),
            mode=context.mode,
        )

    async def _cancel_run(
        self,
        *,
        session: AsyncSession,
        run_id: UUID,
        organization_id: UUID,
        context: _RuntimeContext,
        request_id: str | None,
        reason: str,
    ) -> AgentRuntimeResult:
        await self._repository.update_agent_run(
            session,
            agent_run_id=run_id,
            organization_id=organization_id,
            status=AgentRunStatus.cancelled.value,
            cancelled_at=datetime.now(tz=UTC),
            observations={"cancellation_reason": reason},
            costs={"total_tokens": context.total_tokens, "total_cost_usd": str(context.total_cost_usd)},
            total_cost_usd=float(context.total_cost_usd),
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

    async def _fail_run(
        self,
        *,
        session: AsyncSession,
        run_id: UUID,
        organization_id: UUID,
        context: _RuntimeContext,
        request_id: str | None,
        code: str,
        message: str,
        details: dict[str, Any],
    ) -> AgentRuntimeResult:
        await self._repository.update_agent_run(
            session,
            agent_run_id=run_id,
            organization_id=organization_id,
            status=AgentRunStatus.failed.value,
            completed_at=datetime.now(tz=UTC),
            error_message=message,
            error_details={"code": code, "details": details},
            costs={"total_tokens": context.total_tokens, "total_cost_usd": str(context.total_cost_usd)},
            total_cost_usd=float(context.total_cost_usd),
            observations={"steps_executed": context.steps_executed, "tool_calls_executed": context.tool_calls_executed},
        )
        await self._audit_failed(
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

    async def _audit_started(
        self,
        *,
        session: AsyncSession,
        principal: AuthenticatedPrincipal,
        run_id: UUID,
        request_id: str | None,
        mode: str,
        objective: str,
    ) -> None:
        await self._audit_service.record(
            session,
            organization_id=self._organization_uuid(principal),
            user_id=self._user_uuid(principal),
            action="agent.runtime.started",
            resource_type="agent_run",
            resource_id=run_id,
            request_id=request_id,
            metadata={"mode": mode, "objective_preview": objective[:120]},
        )

    async def _audit_completed(
        self,
        *,
        session: AsyncSession,
        principal: AuthenticatedPrincipal,
        run_id: UUID,
        request_id: str | None,
        context: _RuntimeContext,
        outcome: AgentRuntimeOutcome,
    ) -> None:
        await self._audit_service.record(
            session,
            organization_id=self._organization_uuid(principal),
            user_id=self._user_uuid(principal),
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
            },
        )

    async def _audit_failed(
        self,
        *,
        session: AsyncSession,
        organization_id: UUID,
        run_id: UUID,
        request_id: str | None,
        code: str,
        message: str,
    ) -> None:
        await self._audit_service.record(
            session,
            organization_id=organization_id,
            user_id=None,
            action="agent.runtime.failed",
            resource_type="agent_run",
            resource_id=run_id,
            request_id=request_id,
            metadata={"code": code, "message": message},
        )

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
