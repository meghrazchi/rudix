from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import get_logger, log_agent_event
from app.db.session import get_db_session
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.agents import (
    AgentRunRepository,
    AgentRuntime,
    AgentRuntimeRequest,
    AgentRuntimeResult,
)
from app.domains.agents.services.trace_service import AgentTraceService
from app.domains.quota.schemas.quota_schemas import QuotaType
from app.domains.quota.services.plan_enforcement_service import plan_enforcement_service
from app.models.enums import AgentRunStatus, OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

_logger = get_logger("agent.api")

router = APIRouter(prefix="/agent", tags=["agent"])
agent_runtime = AgentRuntime()
agent_run_repository = AgentRunRepository()
audit_log_service = AuditLogService()
usage_repository = UsageRepository()
agent_trace_service = AgentTraceService()


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
    agent_run_id: str
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


class AgentApprovalQueueItem(BaseModel):
    approval_id: str
    agent_run_id: str
    agent_step_id: str | None = None
    tool_call_id: str | None = None
    requested_by_user_id: str | None = None
    status: str
    risk_level: str | None = None
    tool_name: str | None = None
    request_summary: str | None = None
    request_payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    run_objective: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentApprovalQueueResponse(BaseModel):
    approvals: list[AgentApprovalQueueItem]
    total: int
    limit: int
    offset: int


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
    policy_snapshot: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[AgentStepResponse] = Field(default_factory=list)
    tool_calls: list[AgentToolCallResponse] = Field(default_factory=list)
    approvals: list[AgentApprovalResponse] = Field(default_factory=list)


class AgentRunListItem(BaseModel):
    run_id: str
    status: str
    objective: str | None = None
    total_cost_usd: Decimal | None = None
    trace_request_id: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AgentRunListResponse(BaseModel):
    runs: list[AgentRunListItem]
    total: int
    limit: int
    offset: int


class AgentApprovalDecisionRequest(BaseModel):
    status: str = Field(pattern=r"^(approved|rejected|changes_requested)$")
    reason: str | None = Field(default=None, max_length=600)
    decision_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AgentApprovalCreateRequest(BaseModel):
    request_summary: str | None = Field(default=None, max_length=500)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    expires_in_seconds: int | None = Field(default=None, ge=60, le=86400)
    agent_step_id: str | None = None
    tool_call_id: str | None = None


class AgentApprovalCommentRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("comment must not be blank")
        return stripped


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
        agent_run_id=str(approval.agent_run_id),
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


def _to_approval_queue_item(approval: Any, run_objective: str | None) -> AgentApprovalQueueItem:
    payload = approval.request_payload_json or {}
    return AgentApprovalQueueItem(
        approval_id=str(approval.id),
        agent_run_id=str(approval.agent_run_id),
        agent_step_id=str(approval.agent_step_id) if approval.agent_step_id is not None else None,
        tool_call_id=str(approval.tool_call_id) if approval.tool_call_id is not None else None,
        requested_by_user_id=str(approval.requested_by_user_id)
        if approval.requested_by_user_id is not None
        else None,
        status=approval.status,
        risk_level=payload.get("risk_level")
        if isinstance(payload.get("risk_level"), str)
        else None,
        tool_name=payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else None,
        request_summary=approval.request_summary,
        request_payload=payload,
        expires_at=approval.expires_at,
        run_objective=run_objective,
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
    organization_id, _ = _org_and_user(principal)
    await plan_enforcement_service.ensure_within_limit(
        db_session,
        organization_id=organization_id,
        quota_type=QuotaType.agent_runs,
        requested_amount=1,
        resource="agent runs",
        guidance="Upgrade your plan or reduce agent usage.",
    )
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

    await plan_enforcement_service.record_usage(
        db_session,
        organization_id=organization_id,
        quota_type=QuotaType.agent_runs,
        amount=1,
    )
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
        policy_snapshot=run.policy_snapshot_json or None,
        started_at=run.started_at,
        completed_at=run.completed_at,
        cancelled_at=run.cancelled_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[_to_step_response(step) for step in steps],
        tool_calls=[_to_tool_call_response(tool_call) for tool_call in tool_calls],
        approvals=[_to_approval_response(approval) for approval in approvals],
    )


@router.get("/runs", response_model=AgentRunListResponse)
async def list_agent_runs(
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
    limit: int = 20,
    offset: int = 0,
    status_filter: str | None = None,
) -> AgentRunListResponse:
    _feature_enabled()
    organization_id, user_id = _org_and_user(principal)
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)

    runs = await agent_run_repository.list_agent_runs(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        status=status_filter,
        limit=safe_limit,
        offset=safe_offset,
    )
    total = await agent_run_repository.count_agent_runs(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        status=status_filter,
    )
    return AgentRunListResponse(
        runs=[
            AgentRunListItem(
                run_id=str(run.id),
                status=run.status,
                objective=run.objective,
                total_cost_usd=run.total_cost_usd,
                trace_request_id=run.trace_request_id,
                error_message=run.error_message,
                started_at=run.started_at,
                completed_at=run.completed_at,
                cancelled_at=run.cancelled_at,
                created_at=run.created_at,
                updated_at=run.updated_at,
            )
            for run in runs
        ],
        total=total,
        limit=safe_limit,
        offset=safe_offset,
    )


@router.post("/runs/{run_id}/cancel", response_model=AgentRunDetailResponse)
async def cancel_agent_run(
    run_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentRunDetailResponse:
    _feature_enabled()
    organization_id, user_id = _org_and_user(principal)
    run_uuid = _parse_run_id(run_id)

    run = await agent_run_repository.get_agent_run(
        db_session,
        agent_run_id=run_uuid,
        organization_id=organization_id,
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    if run.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "run_already_terminal",
                "message": "Only queued or running agent runs can be cancelled.",
            },
        )

    updated = await agent_run_repository.update_agent_run(
        db_session,
        agent_run_id=run_uuid,
        organization_id=organization_id,
        status="cancelled",
        cancelled_at=datetime.now(tz=UTC),
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="agent.run.cancel",
        resource_type="agent_run",
        resource_id=run_uuid,
        request_id=_request_id_from_request(request),
        metadata={"run_id": str(run_uuid)},
        required=False,
    )
    log_agent_event(
        event="agent.run.cancel",
        organization_id=str(organization_id),
        user_id=str(user_id),
        run_id=str(run_uuid),
    )
    await db_session.commit()

    steps = await agent_run_repository.list_agent_steps(
        db_session, agent_run_id=updated.id, organization_id=organization_id
    )
    tool_calls = await agent_run_repository.list_agent_tool_calls(
        db_session, agent_run_id=updated.id, organization_id=organization_id
    )
    approvals = await agent_run_repository.list_agent_approvals(
        db_session, agent_run_id=updated.id, organization_id=organization_id
    )
    return AgentRunDetailResponse(
        run_id=str(updated.id),
        organization_id=str(updated.organization_id),
        user_id=str(updated.user_id) if updated.user_id is not None else None,
        status=updated.status,
        surface=updated.surface,
        objective=updated.objective,
        max_steps=updated.max_steps,
        max_parallel_tool_calls=updated.max_parallel_tool_calls,
        budget=updated.budget_json or {},
        costs=updated.costs_json or {},
        outcome=updated.outcome_json or {},
        observations=updated.observations_json or {},
        total_cost_usd=updated.total_cost_usd,
        trace_request_id=updated.trace_request_id,
        error_message=updated.error_message,
        error_details=updated.error_details_json or {},
        policy_snapshot=updated.policy_snapshot_json or None,
        started_at=updated.started_at,
        completed_at=updated.completed_at,
        cancelled_at=updated.cancelled_at,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
        steps=[_to_step_response(s) for s in steps],
        tool_calls=[_to_tool_call_response(tc) for tc in tool_calls],
        approvals=[_to_approval_response(a) for a in approvals],
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


@router.get("/approvals", response_model=AgentApprovalQueueResponse)
async def list_agent_approval_queue(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 20,
    offset: int = 0,
    status_filter: str | None = None,
) -> AgentApprovalQueueResponse:
    _feature_enabled()
    organization_id, _ = _org_and_user(principal)
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)

    approvals = await agent_run_repository.list_org_approvals(
        db_session,
        organization_id=organization_id,
        status=status_filter,
        limit=safe_limit,
        offset=safe_offset,
    )
    total = await agent_run_repository.count_org_approvals(
        db_session,
        organization_id=organization_id,
        status=status_filter,
    )

    # Fetch run objectives for context — one lookup per unique run_id in this page.
    run_ids = {a.agent_run_id for a in approvals}
    run_objectives: dict[Any, str | None] = {}
    for run_id_val in run_ids:
        run = await agent_run_repository.get_agent_run(
            db_session,
            agent_run_id=run_id_val,
            organization_id=organization_id,
        )
        run_objectives[run_id_val] = run.objective if run else None

    return AgentApprovalQueueResponse(
        approvals=[
            _to_approval_queue_item(a, run_objectives.get(a.agent_run_id)) for a in approvals
        ],
        total=total,
        limit=safe_limit,
        offset=safe_offset,
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
    # Expire stale approval before checking status.
    expires_at = approval.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if (
        approval.status == "pending"
        and expires_at
        and expires_at <= datetime.now(tz=UTC)
    ):
        await agent_run_repository.update_agent_approval(
            db_session,
            approval_id=approval_uuid,
            organization_id=organization_id,
            agent_run_id=run_uuid,
            status="expired",
        )
        await db_session.flush()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "approval_expired",
                "message": "This approval request has expired.",
            },
        )

    if approval.status not in {"pending", "changes_requested"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "approval_not_actionable",
                "message": "Only pending or changes_requested approvals can be decided.",
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

    # Transition run status based on decision outcome.
    if run.status == AgentRunStatus.waiting_approval.value:
        if payload.status == "approved":
            await agent_run_repository.update_agent_run(
                db_session,
                agent_run_id=run_uuid,
                organization_id=organization_id,
                status=AgentRunStatus.running.value,
            )
        elif payload.status == "rejected":
            rejection_msg = (
                f"Approval rejected: {payload.reason}"
                if payload.reason
                else "Approval request rejected."
            )
            await agent_run_repository.update_agent_run(
                db_session,
                agent_run_id=run_uuid,
                organization_id=organization_id,
                status=AgentRunStatus.failed.value,
                error_message=rejection_msg,
            )
        # changes_requested: run stays in waiting_approval — no transition needed.

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


@router.post(
    "/runs/{run_id}/approvals",
    response_model=AgentApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_run_approval(
    run_id: str,
    payload: AgentApprovalCreateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentApprovalResponse:
    """Request human approval before executing a side-effect tool call.

    Transitions the run to waiting_approval if not already there.  The agent
    executor is expected to call this endpoint before invoking any tool whose
    effect_policy is side_effect when org policy requires approval.
    """
    _feature_enabled()
    organization_id, user_id = _org_and_user(principal)
    run_uuid = _parse_run_id(run_id)

    run = await agent_run_repository.get_agent_run(
        db_session,
        agent_run_id=run_uuid,
        organization_id=organization_id,
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    if run.status not in {"queued", "planning", "running", "waiting_approval"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "run_not_active",
                "message": "Approval can only be requested for active runs.",
            },
        )

    step_uuid: UUID | None = None
    if payload.agent_step_id is not None:
        try:
            step_uuid = UUID(payload.agent_step_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid agent_step_id",
            ) from exc

    tool_call_uuid: UUID | None = None
    if payload.tool_call_id is not None:
        try:
            tool_call_uuid = UUID(payload.tool_call_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid tool_call_id",
            ) from exc

    expires_at: datetime | None = None
    if payload.expires_in_seconds is not None:
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=payload.expires_in_seconds)

    approval = await agent_run_repository.create_agent_approval(
        db_session,
        organization_id=organization_id,
        agent_run_id=run_uuid,
        agent_step_id=step_uuid,
        tool_call_id=tool_call_uuid,
        requested_by_user_id=user_id,
        request_summary=payload.request_summary,
        request_payload=payload.request_payload,
        expires_at=expires_at,
    )

    if run.status != AgentRunStatus.waiting_approval.value:
        await agent_run_repository.update_agent_run(
            db_session,
            agent_run_id=run_uuid,
            organization_id=organization_id,
            status=AgentRunStatus.waiting_approval.value,
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="agent.approval.requested",
        resource_type="agent_approval",
        resource_id=approval.id,
        request_id=_request_id_from_request(request),
        metadata={
            "run_id": str(run_uuid),
            "approval_id": str(approval.id),
        },
        required=False,
    )
    log_agent_event(
        event="agent.approval.requested",
        organization_id=str(organization_id),
        user_id=str(user_id),
        run_id=str(run_uuid),
        approval_id=str(approval.id),
    )
    await db_session.commit()
    return _to_approval_response(approval)


@router.post(
    "/runs/{run_id}/approvals/{approval_id}/comment",
    response_model=AgentApprovalResponse,
)
async def comment_agent_run_approval(
    run_id: str,
    approval_id: str,
    payload: AgentApprovalCommentRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentApprovalResponse:
    """Add a comment to a pending or changes_requested approval without deciding it."""
    _feature_enabled()
    organization_id, user_id = _org_and_user(principal)
    run_uuid = _parse_run_id(run_id)
    approval_uuid = _parse_approval_id(approval_id)

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
    if approval.status not in {"pending", "changes_requested"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "approval_not_commentable",
                "message": "Comments can only be added to pending or changes_requested approvals.",
            },
        )

    updated = await agent_run_repository.append_approval_comment(
        db_session,
        approval_id=approval_uuid,
        organization_id=organization_id,
        agent_run_id=run_uuid,
        commenter_user_id=user_id,
        comment=payload.comment,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent approval not found"
        )
    await db_session.commit()
    return _to_approval_response(updated)


# ── Trace replay ──────────────────────────────────────────────────────────────


class AgentTraceShareRequest(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    expires_in_hours: int = Field(default=48, ge=1, le=720)


class AgentTraceShareResponse(BaseModel):
    token_id: str
    token: str
    expires_at: str
    label: str | None = None
    share_url: str


class AgentTraceRetentionRequest(BaseModel):
    retain_days: int = Field(default=90, ge=1, le=3650)
    redact_prompts: bool = False
    redact_raw_content: bool = False
    redact_tool_arguments: bool = False


class AgentTraceRetentionResponse(BaseModel):
    organization_id: str
    retain_days: int
    redact_prompts: bool
    redact_raw_content: bool
    redact_tool_arguments: bool
    is_default: bool


async def _load_run_with_relations(
    db_session: AsyncSession,
    run_uuid: UUID,
    organization_id: UUID,
) -> Any:
    run = await agent_run_repository.get_agent_run(
        db_session,
        agent_run_id=run_uuid,
        organization_id=organization_id,
    )
    if run is None:
        return None
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
    # Attach the preloaded collections without triggering lazy-load IO.
    set_committed_value(run, "steps", steps)
    set_committed_value(run, "tool_calls", tool_calls)
    set_committed_value(run, "approvals", approvals)
    return run


@router.get("/runs/{run_id}/trace", response_model=dict)
async def get_agent_run_trace(
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
) -> dict[str, Any]:
    """Return the sanitized trace timeline for an agent run."""
    _feature_enabled()
    organization_id, _ = _org_and_user(principal)
    run_uuid = _parse_run_id(run_id)

    run = await _load_run_with_relations(db_session, run_uuid, organization_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    policy = await agent_trace_service.get_retention_policy(db_session, organization_id)
    return agent_trace_service.build_trace(run, policy)


@router.get("/runs/{run_id}/trace/export", response_model=dict)
async def export_agent_run_trace(
    run_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Return safe-for-support trace metadata with all sensitive content redacted."""
    _feature_enabled()
    organization_id, _ = _org_and_user(principal)
    run_uuid = _parse_run_id(run_id)

    run = await _load_run_with_relations(db_session, run_uuid, organization_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    return agent_trace_service.build_export(run)


@router.post("/runs/{run_id}/trace/share", response_model=AgentTraceShareResponse)
async def share_agent_run_trace(
    run_id: str,
    payload: AgentTraceShareRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentTraceShareResponse:
    """Create a time-limited share token for an agent run trace."""
    _feature_enabled()
    organization_id, user_id = _org_and_user(principal)
    run_uuid = _parse_run_id(run_id)

    run = await agent_run_repository.get_agent_run(
        db_session,
        agent_run_id=run_uuid,
        organization_id=organization_id,
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    share_token, raw_token = await agent_trace_service.create_share_token(
        db_session,
        organization_id=organization_id,
        run_id=run_uuid,
        created_by_user_id=user_id,
        label=payload.label,
        expires_in_hours=payload.expires_in_hours,
    )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="agent.trace.shared",
        resource_type="agent_run",
        resource_id=run_uuid,
        request_id=_request_id_from_request(request),
        metadata={"run_id": run_id, "token_id": str(share_token.id)},
        required=False,
    )
    await db_session.commit()

    base_url = str(request.base_url).rstrip("/")
    share_url = f"{base_url}/agent/traces/shared/{raw_token}"
    return AgentTraceShareResponse(
        token_id=str(share_token.id),
        token=raw_token,
        expires_at=share_token.expires_at.isoformat() if share_token.expires_at else "",
        label=share_token.label,
        share_url=share_url,
    )


public_trace_router = APIRouter(prefix="/agent", tags=["agent"])


@public_trace_router.get("/traces/shared/{token}", response_model=dict)
async def get_shared_agent_trace(
    token: str,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Access a shared agent trace by token. No authentication required; always fully redacted."""
    _feature_enabled()

    share_token = await agent_trace_service.resolve_share_token(db_session, token)
    if share_token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "trace_not_found",
                "message": "Trace share link is invalid or expired.",
            },
        )

    from app.domains.agents.services.trace_service import RetentionPolicySnapshot

    run = await _load_run_with_relations(
        db_session, share_token.agent_run_id, share_token.organization_id
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    policy = RetentionPolicySnapshot.full_redact_policy()
    result = agent_trace_service.build_trace(run, policy)
    result["shared_via_token"] = True
    return result


# ── Trace retention policy (admin) ───────────────────────────────────────────

admin_trace_router = APIRouter(prefix="/admin/agent", tags=["admin-agent"])


@admin_trace_router.get("/trace-retention", response_model=AgentTraceRetentionResponse)
async def get_trace_retention_policy(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentTraceRetentionResponse:
    """Get the org-level trace retention policy. Returns defaults if none set."""
    _feature_enabled()
    organization_id, _ = _org_and_user(principal)
    policy = await agent_trace_service.get_retention_policy(db_session, organization_id)
    return AgentTraceRetentionResponse(
        organization_id=str(organization_id),
        retain_days=policy.retain_days,
        redact_prompts=policy.redact_prompts,
        redact_raw_content=policy.redact_raw_content,
        redact_tool_arguments=policy.redact_tool_arguments,
        is_default=not policy.is_any_redaction_active() and policy.retain_days == 90,
    )


@admin_trace_router.patch("/trace-retention", response_model=AgentTraceRetentionResponse)
async def update_trace_retention_policy(
    payload: AgentTraceRetentionRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentTraceRetentionResponse:
    """Create or update the org-level trace retention policy."""
    _feature_enabled()
    organization_id, user_id = _org_and_user(principal)

    updated = await agent_trace_service.upsert_retention_policy(
        db_session,
        organization_id=organization_id,
        updated_by_user_id=user_id,
        retain_days=payload.retain_days,
        redact_prompts=payload.redact_prompts,
        redact_raw_content=payload.redact_raw_content,
        redact_tool_arguments=payload.redact_tool_arguments,
    )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="agent.trace_retention.updated",
        resource_type="agent_trace_retention_policy",
        resource_id=updated.id,
        request_id=_request_id_from_request(request),
        metadata={
            "retain_days": payload.retain_days,
            "redact_prompts": payload.redact_prompts,
            "redact_raw_content": payload.redact_raw_content,
            "redact_tool_arguments": payload.redact_tool_arguments,
        },
        required=False,
    )
    await db_session.commit()

    policy = await agent_trace_service.get_retention_policy(db_session, organization_id)
    return AgentTraceRetentionResponse(
        organization_id=str(organization_id),
        retain_days=policy.retain_days,
        redact_prompts=policy.redact_prompts,
        redact_raw_content=policy.redact_raw_content,
        redact_tool_arguments=policy.redact_tool_arguments,
        is_default=not policy.is_any_redaction_active() and policy.retain_days == 90,
    )
