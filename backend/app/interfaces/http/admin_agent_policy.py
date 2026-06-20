from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.agents import AgentRunRepository
from app.domains.agents.schemas.agent_policy import (
    AgentPolicyResponse,
    EffectivePolicyResponse,
    ToolPolicyUpsertRequest,
    ToolPolicyUpsertResponse,
)
from app.domains.agents.services.policy_service import AgentPolicyService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin", tags=["admin"])

_policy_service = AgentPolicyService()
_agent_run_repo = AgentRunRepository()
_audit_service = AuditLogService()


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


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


@router.get("/agent-policy", response_model=AgentPolicyResponse)
async def get_agent_policy(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentPolicyResponse:
    organization_id, _ = _org_and_user(principal)
    return await _policy_service.get_policy(db_session, organization_id=organization_id)


@router.put(
    "/agent-policy/tools/{tool_name}",
    response_model=ToolPolicyUpsertResponse,
)
async def upsert_tool_policy(
    tool_name: str,
    payload: ToolPolicyUpsertRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ToolPolicyUpsertResponse:
    organization_id, user_id = _org_and_user(principal)

    normalized = tool_name.strip().lower()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tool_name must not be blank",
        )

    try:
        response = await _policy_service.upsert_tool_override(
            db_session,
            organization_id=organization_id,
            tool_name=normalized,
            updated_by_user_id=user_id,
            request=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    audit_recorded = await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.agent_policy.tool.updated",
        resource_type="agent_tool_policy_override",
        request_id=_request_id(request),
        metadata={
            "tool_name": normalized,
            "enabled": payload.enabled,
            "approval_required": payload.approval_required,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    await db_session.commit()

    return response.model_copy(update={"audit_recorded": audit_recorded})


@router.delete(
    "/agent-policy/tools/{tool_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_tool_policy(
    tool_name: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id, user_id = _org_and_user(principal)

    normalized = tool_name.strip().lower()
    deleted = await _policy_service.delete_tool_override(
        db_session,
        organization_id=organization_id,
        tool_name=normalized,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool policy override not found",
        )

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.agent_policy.tool.deleted",
        resource_type="agent_tool_policy_override",
        request_id=_request_id(request),
        metadata={"tool_name": normalized, "deleted_at": datetime.now(tz=UTC).isoformat()},
        required=False,
    )
    await db_session.commit()


@router.get(
    "/agent-policy/runs/{run_id}/effective-policy",
    response_model=EffectivePolicyResponse,
)
async def get_effective_policy_for_run(
    run_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EffectivePolicyResponse:
    organization_id, _ = _org_and_user(principal)

    try:
        run_uuid = UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found"
        ) from exc

    run = await _agent_run_repo.get_agent_run(
        db_session, agent_run_id=run_uuid, organization_id=organization_id
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")

    return await _policy_service.get_effective_policy_for_run(
        db_session, organization_id=organization_id, run=run
    )
