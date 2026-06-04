from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import get_logger, log_agent_event

_logger = get_logger("agent.api")
from app.db.session import get_db_session
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.agents import (
    AgentRunRepository,
    AgentRuntime,
    AgentRuntimeRequest,
    AgentRuntimeResult,
)
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/agent", tags=["agent"])
agent_runtime = AgentRuntime()
agent_run_repository = AgentRunRepository()
audit_log_service = AuditLogService()
usage_repository = UsageRepository()


class AgentRunCreateRequest(BaseModel):
    agentic_mode: bool = Field(
        default=False,
        description="Explicit switch required to run plan-act-observe agent execution.",
    )
    request: AgentRuntimeRequest


class AgentRunCreateResponse(BaseModel):
    run: AgentRuntimeResult


class AgentStepResponse(BaseModel):
    step_id: str
    sequence: int
    step_name: str
    status: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    observation: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime
    updated_at: datetime


class AgentToolCallResponse(BaseModel):
    tool_call_id: str
    agent_step_id: str | None = None
    call_id: str
    tool_name: str
    surface: str
    effect_policy: str
    status: str
    attempt_number: int
    arguments: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)
    input_size_bytes: int | None = None
    output_size_bytes: int | None = None
    latency_ms: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AgentApprovalResponse(BaseModel):
    approval_id: str
    agent_step_id: str | None = None
    tool_call_id: str | None = None
    requested_by_user_id: str | None = None
    decided_by_user_id: str | None = None
    status: str
    request_summary: str | None = None
    decision_reason: str | None = None
    request_payload: dict[str, Any] = Field(default_factory=dict)
    decision_payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AgentRunDetailResponse(BaseModel):
    run_id: str
    organization_id: str
    user_id: str | None = None
    status: str
    surface: str
    objective: str | None = None
    max_steps: int | None = None
    max_parallel_tool_calls: int | None = None
    budget: dict[str, Any] = Field(default_factory=dict)
    costs: dict[str, Any] = Field(default_factory=dict)
    outcome: dict[str, Any] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(default_factory=dict)
    total_cost_usd: Decimal | None = None
    trace_request_id: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[AgentStepResponse] = Field(default_factory=list)
    tool_calls: list[AgentToolCallResponse] = Field(default_factory=list)
    approvals: list[AgentApprovalResponse] = Field(default_factory=list)


class AgentApprovalDecisionRequest(BaseModel):
    status: str = Field(pattern=r"^(approved|rejected)$")
    reason: str | None = Field(default=None, max_length=600)
    decision_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


def _org_and_user(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id), UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc


def _feature_enabled() -> None:
    if not settings.feature_enable_agents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "feature_not_available",
                "message": "Agentic mode is not enabled for this deployment.",
            },
        )


def _parse_run_id(run_id: str) -> UUID:
    try:
        return UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent run not found",
        ) from exc


def _parse_approval_id(approval_id: str) -> UUID:
    try:
        return UUID(approval_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent approval not found",
        ) from exc


def _to_step_response(step: Any) -> AgentStepResponse:
    return AgentStepResponse(
        step_id=str(step.id),
        sequence=step.sequence,
        step_name=step.step_name,
        status=step.status,
        inputs=step.inputs_json or {},
        outputs=step.outputs_json or {},
        metrics=step.metrics_json or {},
        observation=step.observation_json or {},
        error_message=step.error_message,
        error_details=step.error_details_json or {},
        started_at=step.started_at,
        completed_at=step.completed_at,
        duration_ms=step.duration_ms,
        created_at=step.created_at,
        updated_at=step.updated_at,
    )


def _to_tool_call_response(tool_call: Any) -> AgentToolCallResponse:
    return AgentToolCallResponse(
        tool_call_id=str(tool_call.id),
        agent_step_id=str(tool_call.agent_step_id) if tool_call.agent_step_id is not None else None,
        call_id=tool_call.call_id,
        tool_name=tool_call.tool_name,
        surface=tool_call.surface,
        effect_policy=tool_call.effect_policy,
        status=tool_call.status,
        attempt_number=tool_call.attempt_number,
        arguments=tool_call.arguments_json or {},
        output=tool_call.output_json or {},
        error=tool_call.error_json or {},
        input_size_bytes=tool_call.input_size_bytes,
        output_size_bytes=tool_call.output_size_bytes,
        latency_ms=tool_call.latency_ms,
        started_at=tool_call.started_at,
        completed_at=tool_call.completed_at,
        created_at=tool_call.created_at,
        updated_at=tool_call.updated_at,
    )


def _to_approval_response(approval: Any) -> AgentApprovalResponse:
    return AgentApprovalResponse(
        approval_id=str(approval.id),
        agent_step_id=str(approval.agent_step_id) if approval.agent_step_id is not None else None,
        tool_call_id=str(approval.tool_call_id) if approval.tool_call_id is not None else None,
        requested_by_user_id=str(approval.requested_by_user_id)
        if approval.requested_by_user_id is not None
        else None,
        decided_by_user_id=str(approval.decided_by_user_id)
        if approval.decided_by_user_id is not None
        else None,
        status=approval.status,
        request_summary=approval.request_summary,
        decision_reason=approval.decision_reason,
        request_payload=approval.request_payload_json or {},
        decision_payload=approval.decision_payload_json or {},
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


@router.post("/runs", response_model=AgentRunCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_run(
    payload: AgentRunCreateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentRunCreateResponse:
    _feature_enabled()
    if not payload.agentic_mode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "agentic_mode_required",
                "message": "Set agentic_mode=true to execute agent runs.",
            },
        )

    request_id = _request_id_from_request(request)
    try:
        run_result = await agent_runtime.execute(
            session=db_session,
            principal=principal,
            request=payload.request,
            request_id=request_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _logger.exception(
            "agent.runtime.execute.failed",
            error=exc.__class__.__name__,
            error_detail=str(exc),
            request_id=request_id,
            organization_id=principal.organization_id,
            user_id=principal.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agent_runtime_unavailable",
                "message": "Unable to execute agent run. Retry shortly.",
                "request_id": request_id,
            },
        ) from exc

    await db_session.commit()
    return AgentRunCreateResponse(run=run_result)


@router.get("/runs/{run_id}", response_model=AgentRunDetailResponse)
async def get_agent_run(
    run_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentRunDetailResponse:
    _feature_enabled()
    organization_id, _ = _org_and_user(principal)
    run_uuid = _parse_run_id(run_id)

    run = await agent_run_repository.get_agent_run(
        db_session,
        agent_run_id=run_uuid,
        organization_id=organization_id,
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    steps = await agent_run_repository.list_agent_steps(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_id,
    )
    tool_calls = await agent_run_repository.list_agent_tool_calls(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_id,
    )
    approvals = await agent_run_repository.list_agent_approvals(
        db_session,
        agent_run_id=run.id,
        organization_id=organization_id,
    )

    return AgentRunDetailResponse(
        run_id=str(run.id),
        organization_id=str(run.organization_id),
        user_id=str(run.user_id) if run.user_id is not None else None,
        status=run.status,
        surface=run.surface,
        objective=run.objective,
        max_steps=run.max_steps,
        max_parallel_tool_calls=run.max_parallel_tool_calls,
        budget=run.budget_json or {},
        costs=run.costs_json or {},
        outcome=run.outcome_json or {},
        observations=run.observations_json or {},
        total_cost_usd=run.total_cost_usd,
        trace_request_id=run.trace_request_id,
        error_message=run.error_message,
        error_details=run.error_details_json or {},
        started_at=run.started_at,
        completed_at=run.completed_at,
        cancelled_at=run.cancelled_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[_to_step_response(step) for step in steps],
        tool_calls=[_to_tool_call_response(tool_call) for tool_call in tool_calls],
        approvals=[_to_approval_response(approval) for approval in approvals],
    )


@router.get("/runs/{run_id}/stream")
async def stream_agent_run(
    run_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
) -> dict[str, str]:
    del run_id, principal
    _feature_enabled()
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={
            "code": "stream_not_implemented",
            "message": "Agent run streaming is not implemented yet.",
        },
    )


@router.post(
    "/runs/{run_id}/approvals/{approval_id}/decision", response_model=AgentApprovalResponse
)
async def decide_agent_run_approval(
    run_id: str,
    approval_id: str,
    payload: AgentApprovalDecisionRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentApprovalResponse:
    _feature_enabled()
    organization_id, decided_by_user_id = _org_and_user(principal)
    run_uuid = _parse_run_id(run_id)
    approval_uuid = _parse_approval_id(approval_id)

    run = await agent_run_repository.get_agent_run(
        db_session,
        agent_run_id=run_uuid,
        organization_id=organization_id,
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    approval = await agent_run_repository.get_agent_approval(
        db_session,
        approval_id=approval_uuid,
        organization_id=organization_id,
        agent_run_id=run_uuid,
    )
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent approval not found"
        )
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "approval_not_pending",
                "message": "Only pending approvals can be decided.",
            },
        )

    updated = await agent_run_repository.update_agent_approval(
        db_session,
        approval_id=approval_uuid,
        organization_id=organization_id,
        agent_run_id=run_uuid,
        status=payload.status,
        decided_by_user_id=decided_by_user_id,
        decision_reason=payload.reason,
        decision_payload=payload.decision_payload,
        decided_at=datetime.now(tz=UTC),
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent approval not found"
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=decided_by_user_id,
        action=f"agent.approval.{payload.status}",
        resource_type="agent_approval",
        resource_id=approval_uuid,
        request_id=_request_id_from_request(request),
        metadata={
            "run_id": str(run_uuid),
            "approval_id": str(approval_uuid),
            "decision_reason": payload.reason,
        },
        required=False,
    )
    try:
        await usage_repository.create_usage_event(
            db_session,
            organization_id=organization_id,
            user_id=decided_by_user_id,
            event_type="agent.approval",
            metadata={
                "run_id": str(run_uuid),
                "approval_id": str(approval_uuid),
                "status": payload.status,
                "request_id": _request_id_from_request(request),
            },
        )
    except Exception:
        # Keep approval decision path non-blocking if observability write fails.
        pass
    log_agent_event(
        event=f"agent.approval.{payload.status}",
        organization_id=str(organization_id),
        user_id=str(decided_by_user_id),
        run_id=str(run_uuid),
        approval_id=str(approval_uuid),
    )
    await db_session.commit()
    return _to_approval_response(updated)
