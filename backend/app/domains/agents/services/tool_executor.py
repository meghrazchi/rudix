from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.agents.repositories import AgentRunRepository
from app.domains.agents.schemas import (
    ToolCall,
    ToolErrorCode,
    ToolResult,
    authorize_tool_call,
    build_safe_tool_error_result,
    build_tool_success_result,
    redact_tool_payload,
    validate_tool_call_budget,
)
from app.domains.agents.services.tool_registry import ToolHandler, ToolRegistry
from app.models.enums import AgentApprovalStatus, AgentToolCallStatus

_logger = get_logger("services.agent.tools")


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


class AgentToolExecutor:
    """Shared internal execution contract for API runtime and MCP adapters."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        repository: AgentRunRepository | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository or AgentRunRepository()
        self._audit_service = audit_service or AuditLogService()
        self._transient_call_counts: dict[tuple[str, str], int] = {}

    async def execute(
        self,
        *,
        session: AsyncSession | None,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
        request_id: str | None = None,
    ) -> ToolResult:
        registered = self._registry.resolve(call.tool_name)
        if registered is None:
            return build_safe_tool_error_result(
                call,
                code=ToolErrorCode.tool_unavailable,
                safe_message="Tool is not registered or unavailable.",
                request_id=request_id,
                details={"tool_name": call.tool_name},
            )

        spec = registered.spec
        handler = registered.handler

        persisted_call_id: UUID | None = None
        started_at_dt = datetime.now(tz=UTC)
        started_at_perf = perf_counter()

        try:
            authorize_tool_call(spec, call, principal)
            validate_tool_call_budget(spec, call)
            await self._enforce_call_budget(session=session, call=call)
            await self._enforce_approval_requirement(session=session, call=call)

            persisted_call_id = await self._persist_started_tool_call(
                session=session,
                call=call,
                principal=principal,
                request_id=request_id,
                started_at=started_at_dt,
            )

            raw_output = await self._run_with_timeout(handler=handler, call=call, principal=principal, timeout_ms=spec.budget.timeout_ms)
            safe_output = redact_tool_payload(spec, raw_output or {}, is_output=True)
            result = build_tool_success_result(
                spec,
                call,
                output=safe_output,
                latency_ms=int((perf_counter() - started_at_perf) * 1000),
            )
            await self._persist_finished_tool_call(
                session=session,
                call=call,
                persisted_call_id=persisted_call_id,
                status=AgentToolCallStatus.succeeded.value,
                result=result,
                completed_at=datetime.now(tz=UTC),
            )
            await self._audit_tool_event(
                session=session,
                call=call,
                principal=principal,
                request_id=request_id,
                action="agent.tool_call.succeeded",
                metadata={
                    "tool_name": call.tool_name,
                    "surface": call.surface.value,
                    "effect_policy": spec.effect_policy.value,
                    "latency_ms": result.latency_ms,
                    "success": True,
                },
            )
            return result
        except (ValueError, AuthorizationError, TimeoutError) as exc:
            result = self._safe_failure_result(
                call=call,
                exc=exc,
                request_id=request_id,
                latency_ms=int((perf_counter() - started_at_perf) * 1000),
            )
            await self._persist_finished_tool_call(
                session=session,
                call=call,
                persisted_call_id=persisted_call_id,
                status=AgentToolCallStatus.failed.value,
                result=result,
                completed_at=datetime.now(tz=UTC),
            )
            await self._audit_tool_event(
                session=session,
                call=call,
                principal=principal,
                request_id=request_id,
                action="agent.tool_call.failed",
                metadata={
                    "tool_name": call.tool_name,
                    "surface": call.surface.value,
                    "effect_policy": spec.effect_policy.value,
                    "success": False,
                    "error_code": result.error.code.value if result.error else None,
                },
            )
            return result
        except Exception as exc:
            _logger.exception(
                "agent.tool_call.unhandled",
                tool_name=call.tool_name,
                call_id=call.call_id,
                run_id=call.run_id,
                request_id=request_id,
                error=exc.__class__.__name__,
            )
            result = build_safe_tool_error_result(
                call,
                code=ToolErrorCode.internal_error,
                safe_message="Tool execution failed unexpectedly.",
                request_id=request_id,
                retryable=False,
                details={"error": exc.__class__.__name__},
                latency_ms=int((perf_counter() - started_at_perf) * 1000),
            )
            await self._persist_finished_tool_call(
                session=session,
                call=call,
                persisted_call_id=persisted_call_id,
                status=AgentToolCallStatus.failed.value,
                result=result,
                completed_at=datetime.now(tz=UTC),
            )
            await self._audit_tool_event(
                session=session,
                call=call,
                principal=principal,
                request_id=request_id,
                action="agent.tool_call.failed",
                metadata={
                    "tool_name": call.tool_name,
                    "surface": call.surface.value,
                    "effect_policy": spec.effect_policy.value,
                    "success": False,
                    "error_code": result.error.code.value if result.error else None,
                },
            )
            return result

    async def _run_with_timeout(
        self,
        *,
        handler: ToolHandler,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
        timeout_ms: int,
    ) -> dict[str, Any] | None:
        maybe_result = handler(call, principal)
        if asyncio.iscoroutine(maybe_result):
            try:
                awaited_result = await asyncio.wait_for(maybe_result, timeout=timeout_ms / 1000)
            except TimeoutError as exc:
                raise TimeoutError("Tool execution timed out") from exc
            if awaited_result is None:
                return None
            if not isinstance(awaited_result, dict):
                raise ValueError("Tool handler must return a JSON object dictionary")
            return awaited_result
        if maybe_result is None:
            return None
        if not isinstance(maybe_result, dict):
            raise ValueError("Tool handler must return a JSON object dictionary")
        return maybe_result

    async def _enforce_call_budget(self, *, session: AsyncSession | None, call: ToolCall) -> None:
        spec = self._registry.get_spec(call.tool_name)
        if spec is None:
            raise ValueError("Tool specification is missing")

        key = (call.run_id, call.tool_name)
        existing_count = self._transient_call_counts.get(key, 0)
        if session is not None:
            run_uuid = _parse_uuid(call.run_id)
            org_uuid = _parse_uuid(call.organization_id)
            if run_uuid is not None and org_uuid is not None:
                existing_count = await self._repository.count_agent_tool_calls(
                    session,
                    agent_run_id=run_uuid,
                    organization_id=org_uuid,
                    tool_name=call.tool_name,
                )
        if existing_count >= spec.budget.max_calls_per_run:
            raise ValueError("Tool call budget exceeded for this run")
        self._transient_call_counts[key] = existing_count + 1

    async def _enforce_approval_requirement(self, *, session: AsyncSession | None, call: ToolCall) -> None:
        spec = self._registry.get_spec(call.tool_name)
        if spec is None:
            raise ValueError("Tool specification is missing")
        if not spec.approval_required:
            return
        if call.approval_id is None:
            raise ValueError("approval_id is required for this tool")
        if session is None:
            raise AuthorizationError("Approval validation requires an active database session")
        approval_uuid = _parse_uuid(call.approval_id)
        run_uuid = _parse_uuid(call.run_id)
        org_uuid = _parse_uuid(call.organization_id)
        if approval_uuid is None or run_uuid is None or org_uuid is None:
            raise AuthorizationError("approval_id/run_id/organization_id must be valid UUID values")
        approval = await self._repository.get_agent_approval(
            session,
            approval_id=approval_uuid,
            organization_id=org_uuid,
            agent_run_id=run_uuid,
        )
        if approval is None:
            raise AuthorizationError("Approval was not found for this organization and run")
        if approval.status != AgentApprovalStatus.approved.value:
            raise AuthorizationError("Approval is not in approved state")

    async def _persist_started_tool_call(
        self,
        *,
        session: AsyncSession | None,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
        request_id: str | None,
        started_at: datetime,
    ) -> UUID | None:
        if session is None:
            return None
        run_uuid = _parse_uuid(call.run_id)
        org_uuid = _parse_uuid(call.organization_id)
        user_uuid = _parse_uuid(call.user_id)
        if run_uuid is None or org_uuid is None:
            return None
        spec = self._registry.get_spec(call.tool_name)
        if spec is None:
            return None
        persisted = await self._repository.create_agent_tool_call(
            session,
            agent_run_id=run_uuid,
            organization_id=org_uuid,
            user_id=user_uuid,
            tool_name=call.tool_name,
            surface=call.surface.value,
            effect_policy=spec.effect_policy.value,
            status=AgentToolCallStatus.running.value,
            call_id=call.call_id,
            idempotency_key=call.idempotency_key,
            arguments=call.arguments,
            started_at=started_at,
        )
        await self._audit_tool_event(
            session=session,
            call=call,
            principal=principal,
            request_id=request_id,
            action="agent.tool_call.started",
            metadata={
                "tool_name": call.tool_name,
                "surface": call.surface.value,
                "effect_policy": spec.effect_policy.value,
                "call_id": call.call_id,
            },
        )
        return persisted.id

    async def _persist_finished_tool_call(
        self,
        *,
        session: AsyncSession | None,
        call: ToolCall,
        persisted_call_id: UUID | None,
        status: str,
        result: ToolResult,
        completed_at: datetime,
    ) -> None:
        if session is None or persisted_call_id is None:
            return
        org_uuid = _parse_uuid(call.organization_id)
        if org_uuid is None:
            return
        await self._repository.update_agent_tool_call(
            session,
            tool_call_id=persisted_call_id,
            organization_id=org_uuid,
            status=status,
            output=result.output or {},
            error=result.error.model_dump(mode="json") if result.error else {},
            output_size_bytes=len(json.dumps(result.output or {}, ensure_ascii=False, default=str).encode("utf-8")),
            latency_ms=result.latency_ms,
            completed_at=completed_at,
        )

    async def _audit_tool_event(
        self,
        *,
        session: AsyncSession | None,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
        request_id: str | None,
        action: str,
        metadata: dict[str, Any],
    ) -> None:
        if session is None:
            return
        org_uuid = _parse_uuid(call.organization_id)
        user_uuid = _parse_uuid(call.user_id)
        if org_uuid is None:
            return
        await self._audit_service.record(
            session,
            organization_id=org_uuid,
            user_id=user_uuid,
            action=action,
            resource_type="agent_tool_call",
            resource_id=call.call_id,
            request_id=request_id,
            metadata={
                **metadata,
                "run_id": call.run_id,
                "principal_user_id": principal.user_id,
                "principal_org_id": principal.organization_id,
            },
            required=False,
        )

    def _safe_failure_result(
        self,
        *,
        call: ToolCall,
        exc: Exception,
        request_id: str | None,
        latency_ms: int,
    ) -> ToolResult:
        if isinstance(exc, AuthorizationError):
            return build_safe_tool_error_result(
                call,
                code=ToolErrorCode.authorization_failed,
                safe_message="Tool call is not authorized.",
                request_id=request_id,
                retryable=False,
                details={"error": str(exc)},
                latency_ms=latency_ms,
            )
        if isinstance(exc, TimeoutError):
            return build_safe_tool_error_result(
                call,
                code=ToolErrorCode.tool_unavailable,
                safe_message="Tool execution timed out.",
                request_id=request_id,
                retryable=True,
                details={"error": "timeout"},
                latency_ms=latency_ms,
            )
        message = str(exc)
        if "max_input_bytes" in message or "max_output_bytes" in message or "budget exceeded" in message:
            code = ToolErrorCode.budget_exceeded
        else:
            code = ToolErrorCode.validation_failed
        return build_safe_tool_error_result(
            call,
            code=code,
            safe_message="Tool call validation failed.",
            request_id=request_id,
            retryable=False,
            details={"error": message},
            latency_ms=latency_ms,
        )
