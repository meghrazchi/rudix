from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.services.audit_service import sanitize_metadata
from app.models.agent import AgentApproval, AgentRun, AgentStep, AgentToolCall
from app.models.enums import (
    AgentApprovalStatus,
    AgentRunStatus,
    AgentStepStatus,
    AgentToolCallStatus,
)

_ALLOWED_SURFACES = {"api", "mcp"}
_ALLOWED_EFFECT_POLICIES = {"read_only", "side_effect"}


def _payload_size_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def _sanitize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    return sanitize_metadata(payload)


def _validate_value(value: str, *, allowed_values: set[str], field_name: str) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed_values:
        raise ValueError(f"Unsupported {field_name}: {value}")
    return normalized


def _hash_idempotency_key(idempotency_key: str | None) -> str | None:
    if idempotency_key is None:
        return None
    normalized = idempotency_key.strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class AgentRunRepository:
    async def create_agent_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        status: str = AgentRunStatus.queued.value,
        surface: str = "api",
        objective: str | None = None,
        prompt_template_version_id: UUID | None = None,
        max_steps: int | None = None,
        max_parallel_tool_calls: int | None = None,
        budget: dict[str, Any] | None = None,
        costs: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        observations: dict[str, Any] | None = None,
        total_cost_usd: float | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        cancelled_at: datetime | None = None,
        trace_request_id: str | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> AgentRun:
        normalized_status = _validate_value(
            status,
            allowed_values={item.value for item in AgentRunStatus},
            field_name="agent run status",
        )
        normalized_surface = _validate_value(
            surface,
            allowed_values=_ALLOWED_SURFACES,
            field_name="agent run surface",
        )
        agent_run = AgentRun(
            organization_id=organization_id,
            user_id=user_id,
            status=normalized_status,
            surface=normalized_surface,
            objective=objective,
            prompt_template_version_id=prompt_template_version_id,
            max_steps=max_steps,
            max_parallel_tool_calls=max_parallel_tool_calls,
            budget_json=_sanitize_payload(budget),
            costs_json=_sanitize_payload(costs),
            outcome_json=_sanitize_payload(outcome),
            observations_json=_sanitize_payload(observations),
            total_cost_usd=total_cost_usd,
            started_at=started_at,
            completed_at=completed_at,
            cancelled_at=cancelled_at,
            trace_request_id=trace_request_id,
            error_message=error_message,
            error_details_json=_sanitize_payload(error_details),
        )
        session.add(agent_run)
        await session.flush()
        await session.refresh(agent_run)
        return agent_run

    async def get_agent_run(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
    ) -> AgentRun | None:
        result = await session.execute(
            select(AgentRun).where(
                AgentRun.id == agent_run_id,
                AgentRun.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_agent_runs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AgentRun]:
        statement = select(AgentRun).where(AgentRun.organization_id == organization_id)
        if user_id is not None:
            statement = statement.where(AgentRun.user_id == user_id)
        if status is not None:
            normalized_status = _validate_value(
                status,
                allowed_values={item.value for item in AgentRunStatus},
                field_name="agent run status",
            )
            statement = statement.where(AgentRun.status == normalized_status)
        result = await session.execute(
            statement.order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_agent_runs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None = None,
        status: str | None = None,
    ) -> int:
        statement = select(func.count(AgentRun.id)).where(
            AgentRun.organization_id == organization_id
        )
        if user_id is not None:
            statement = statement.where(AgentRun.user_id == user_id)
        if status is not None:
            normalized_status = _validate_value(
                status,
                allowed_values={item.value for item in AgentRunStatus},
                field_name="agent run status",
            )
            statement = statement.where(AgentRun.status == normalized_status)
        result = await session.execute(statement)
        return int(result.scalar_one())

    async def update_agent_run(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
        status: str | None = None,
        objective: str | None = None,
        budget: dict[str, Any] | None = None,
        costs: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        observations: dict[str, Any] | None = None,
        total_cost_usd: float | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        cancelled_at: datetime | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        run = await session.scalar(
            select(AgentRun).where(
                AgentRun.id == agent_run_id,
                AgentRun.organization_id == organization_id,
            )
        )
        if run is None:
            return None
        if status is not None:
            run.status = _validate_value(
                status,
                allowed_values={item.value for item in AgentRunStatus},
                field_name="agent run status",
            )
        if objective is not None:
            run.objective = objective
        if budget is not None:
            run.budget_json = _sanitize_payload(budget)
        if costs is not None:
            run.costs_json = _sanitize_payload(costs)
        if outcome is not None:
            run.outcome_json = _sanitize_payload(outcome)
        if observations is not None:
            run.observations_json = _sanitize_payload(observations)
        if total_cost_usd is not None:
            run.total_cost_usd = Decimal(str(total_cost_usd))
        if started_at is not None:
            run.started_at = started_at
        if completed_at is not None:
            run.completed_at = completed_at
        if cancelled_at is not None:
            run.cancelled_at = cancelled_at
        if error_message is not None:
            run.error_message = error_message
        if error_details is not None:
            run.error_details_json = _sanitize_payload(error_details)
        await session.flush()
        await session.refresh(run)
        return run

    async def create_agent_step(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
        user_id: UUID | None,
        sequence: int,
        step_name: str,
        status: str = AgentStepStatus.queued.value,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        observation: dict[str, Any] | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
    ) -> AgentStep:
        normalized_status = _validate_value(
            status,
            allowed_values={item.value for item in AgentStepStatus},
            field_name="agent step status",
        )
        step = AgentStep(
            agent_run_id=agent_run_id,
            organization_id=organization_id,
            user_id=user_id,
            sequence=sequence,
            step_name=step_name,
            status=normalized_status,
            inputs_json=_sanitize_payload(inputs),
            outputs_json=_sanitize_payload(outputs),
            metrics_json=_sanitize_payload(metrics),
            observation_json=_sanitize_payload(observation),
            error_message=error_message,
            error_details_json=_sanitize_payload(error_details),
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
        session.add(step)
        await session.flush()
        await session.refresh(step)
        return step

    async def list_agent_steps(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
    ) -> list[AgentStep]:
        result = await session.execute(
            select(AgentStep)
            .where(
                AgentStep.agent_run_id == agent_run_id,
                AgentStep.organization_id == organization_id,
            )
            .order_by(AgentStep.sequence.asc(), AgentStep.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_agent_step(
        self,
        session: AsyncSession,
        *,
        agent_step_id: UUID,
        organization_id: UUID,
        status: str | None = None,
        outputs: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        observation: dict[str, Any] | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
    ) -> AgentStep | None:
        step = await session.scalar(
            select(AgentStep).where(
                AgentStep.id == agent_step_id,
                AgentStep.organization_id == organization_id,
            )
        )
        if step is None:
            return None
        if status is not None:
            step.status = _validate_value(
                status,
                allowed_values={item.value for item in AgentStepStatus},
                field_name="agent step status",
            )
        if outputs is not None:
            step.outputs_json = _sanitize_payload(outputs)
        if metrics is not None:
            step.metrics_json = _sanitize_payload(metrics)
        if observation is not None:
            step.observation_json = _sanitize_payload(observation)
        if error_message is not None:
            step.error_message = error_message
        if error_details is not None:
            step.error_details_json = _sanitize_payload(error_details)
        if started_at is not None:
            step.started_at = started_at
        if completed_at is not None:
            step.completed_at = completed_at
        if duration_ms is not None:
            step.duration_ms = duration_ms
        await session.flush()
        await session.refresh(step)
        return step

    async def create_agent_tool_call(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
        user_id: UUID | None,
        tool_name: str,
        surface: str,
        effect_policy: str,
        status: str = AgentToolCallStatus.queued.value,
        agent_step_id: UUID | None = None,
        call_id: str | None = None,
        attempt_number: int = 1,
        idempotency_key: str | None = None,
        arguments: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        latency_ms: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> AgentToolCall:
        normalized_surface = _validate_value(
            surface,
            allowed_values=_ALLOWED_SURFACES,
            field_name="agent tool call surface",
        )
        normalized_effect_policy = _validate_value(
            effect_policy,
            allowed_values=_ALLOWED_EFFECT_POLICIES,
            field_name="agent tool call effect_policy",
        )
        normalized_status = _validate_value(
            status,
            allowed_values={item.value for item in AgentToolCallStatus},
            field_name="agent tool call status",
        )
        safe_arguments = _sanitize_payload(arguments)
        safe_output = _sanitize_payload(output)
        safe_error = _sanitize_payload(error)
        tool_call = AgentToolCall(
            agent_run_id=agent_run_id,
            agent_step_id=agent_step_id,
            organization_id=organization_id,
            user_id=user_id,
            call_id=call_id or str(uuid4()),
            tool_name=tool_name,
            surface=normalized_surface,
            effect_policy=normalized_effect_policy,
            status=normalized_status,
            attempt_number=attempt_number,
            idempotency_key_hash=_hash_idempotency_key(idempotency_key),
            arguments_json=safe_arguments,
            output_json=safe_output,
            error_json=safe_error,
            input_size_bytes=_payload_size_bytes(safe_arguments),
            output_size_bytes=_payload_size_bytes(safe_output),
            latency_ms=latency_ms,
            started_at=started_at,
            completed_at=completed_at,
        )
        session.add(tool_call)
        await session.flush()
        await session.refresh(tool_call)
        return tool_call

    async def get_agent_tool_call_by_call_id(
        self,
        session: AsyncSession,
        *,
        call_id: str,
        organization_id: UUID,
    ) -> AgentToolCall | None:
        result = await session.execute(
            select(AgentToolCall).where(
                AgentToolCall.call_id == call_id,
                AgentToolCall.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_agent_tool_calls(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
    ) -> list[AgentToolCall]:
        result = await session.execute(
            select(AgentToolCall)
            .where(
                AgentToolCall.agent_run_id == agent_run_id,
                AgentToolCall.organization_id == organization_id,
            )
            .order_by(AgentToolCall.created_at.asc(), AgentToolCall.id.asc())
        )
        return list(result.scalars().all())

    async def count_agent_tool_calls(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
        tool_name: str | None = None,
    ) -> int:
        statement = select(func.count(AgentToolCall.id)).where(
            AgentToolCall.agent_run_id == agent_run_id,
            AgentToolCall.organization_id == organization_id,
        )
        if tool_name is not None:
            statement = statement.where(AgentToolCall.tool_name == tool_name)
        result = await session.execute(statement)
        return int(result.scalar_one())

    async def update_agent_tool_call(
        self,
        session: AsyncSession,
        *,
        tool_call_id: UUID,
        organization_id: UUID,
        status: str | None = None,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        output_size_bytes: int | None = None,
        latency_ms: int | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> AgentToolCall | None:
        tool_call = await session.scalar(
            select(AgentToolCall).where(
                AgentToolCall.id == tool_call_id,
                AgentToolCall.organization_id == organization_id,
            )
        )
        if tool_call is None:
            return None
        if status is not None:
            normalized_status = _validate_value(
                status,
                allowed_values={item.value for item in AgentToolCallStatus},
                field_name="agent tool call status",
            )
            tool_call.status = normalized_status
        if output is not None:
            tool_call.output_json = _sanitize_payload(output)
        if error is not None:
            tool_call.error_json = _sanitize_payload(error)
        if output_size_bytes is not None:
            tool_call.output_size_bytes = output_size_bytes
        if latency_ms is not None:
            tool_call.latency_ms = latency_ms
        if started_at is not None:
            tool_call.started_at = started_at
        if completed_at is not None:
            tool_call.completed_at = completed_at
        await session.flush()
        await session.refresh(tool_call)
        return tool_call

    async def get_agent_approval(
        self,
        session: AsyncSession,
        *,
        approval_id: UUID,
        organization_id: UUID,
        agent_run_id: UUID,
    ) -> AgentApproval | None:
        result = await session.execute(
            select(AgentApproval).where(
                AgentApproval.id == approval_id,
                AgentApproval.organization_id == organization_id,
                AgentApproval.agent_run_id == agent_run_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_agent_approval(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        agent_run_id: UUID,
        status: str = AgentApprovalStatus.pending.value,
        agent_step_id: UUID | None = None,
        tool_call_id: UUID | None = None,
        requested_by_user_id: UUID | None = None,
        decided_by_user_id: UUID | None = None,
        request_summary: str | None = None,
        decision_reason: str | None = None,
        request_payload: dict[str, Any] | None = None,
        decision_payload: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        decided_at: datetime | None = None,
    ) -> AgentApproval:
        normalized_status = _validate_value(
            status,
            allowed_values={item.value for item in AgentApprovalStatus},
            field_name="agent approval status",
        )
        approval = AgentApproval(
            organization_id=organization_id,
            agent_run_id=agent_run_id,
            agent_step_id=agent_step_id,
            tool_call_id=tool_call_id,
            requested_by_user_id=requested_by_user_id,
            decided_by_user_id=decided_by_user_id,
            status=normalized_status,
            request_summary=request_summary,
            decision_reason=decision_reason,
            request_payload_json=_sanitize_payload(request_payload),
            decision_payload_json=_sanitize_payload(decision_payload),
            expires_at=expires_at,
            decided_at=decided_at,
        )
        session.add(approval)
        await session.flush()
        await session.refresh(approval)
        return approval

    async def list_agent_approvals(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
    ) -> list[AgentApproval]:
        result = await session.execute(
            select(AgentApproval)
            .where(
                AgentApproval.agent_run_id == agent_run_id,
                AgentApproval.organization_id == organization_id,
            )
            .order_by(AgentApproval.created_at.asc(), AgentApproval.id.asc())
        )
        return list(result.scalars().all())

    async def list_org_approvals(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AgentApproval]:
        statement = select(AgentApproval).where(
            AgentApproval.organization_id == organization_id
        )
        if status is not None:
            normalized = _validate_value(
                status,
                allowed_values={item.value for item in AgentApprovalStatus},
                field_name="agent approval status",
            )
            statement = statement.where(AgentApproval.status == normalized)
        result = await session.execute(
            statement.order_by(AgentApproval.created_at.asc(), AgentApproval.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_org_approvals(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
    ) -> int:
        statement = select(func.count(AgentApproval.id)).where(
            AgentApproval.organization_id == organization_id
        )
        if status is not None:
            normalized = _validate_value(
                status,
                allowed_values={item.value for item in AgentApprovalStatus},
                field_name="agent approval status",
            )
            statement = statement.where(AgentApproval.status == normalized)
        result = await session.execute(statement)
        return int(result.scalar_one())

    async def expire_pending_approvals(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID | None = None,
        now: datetime | None = None,
    ) -> int:
        cutoff = now or datetime.now(tz=UTC)
        statement = (
            update(AgentApproval)
            .where(
                AgentApproval.status == AgentApprovalStatus.pending.value,
                AgentApproval.expires_at.is_not(None),
                AgentApproval.expires_at <= cutoff,
            )
            .values(status=AgentApprovalStatus.expired.value)
        )
        if organization_id is not None:
            statement = statement.where(AgentApproval.organization_id == organization_id)
        result = await session.execute(statement)
        return result.rowcount

    async def update_agent_approval(
        self,
        session: AsyncSession,
        *,
        approval_id: UUID,
        organization_id: UUID,
        agent_run_id: UUID,
        status: str | None = None,
        decided_by_user_id: UUID | None = None,
        decision_reason: str | None = None,
        decision_payload: dict[str, Any] | None = None,
        decided_at: datetime | None = None,
    ) -> AgentApproval | None:
        approval = await session.scalar(
            select(AgentApproval).where(
                AgentApproval.id == approval_id,
                AgentApproval.organization_id == organization_id,
                AgentApproval.agent_run_id == agent_run_id,
            )
        )
        if approval is None:
            return None
        if status is not None:
            approval.status = _validate_value(
                status,
                allowed_values={item.value for item in AgentApprovalStatus},
                field_name="agent approval status",
            )
        if decided_by_user_id is not None:
            approval.decided_by_user_id = decided_by_user_id
        if decision_reason is not None:
            approval.decision_reason = decision_reason
        if decision_payload is not None:
            approval.decision_payload_json = _sanitize_payload(decision_payload)
        if decided_at is not None:
            approval.decided_at = decided_at
        await session.flush()
        await session.refresh(approval)
        return approval
