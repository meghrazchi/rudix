from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.schemas.governance import (
    GovernancePolicyResponse,
    GovernancePolicyUpdateRequest,
    GovernancePolicyUpdateResponse,
)
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.governance_service import GovernancePolicyService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin", tags=["admin"])
audit_log_service = AuditLogService()
governance_service = GovernancePolicyService()


def _organization_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal organization context is invalid",
        ) from exc


def _user_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal user context is invalid",
        ) from exc


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


@router.get("/governance", response_model=GovernancePolicyResponse)
async def get_governance_policy(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GovernancePolicyResponse:
    organization_id = _organization_id_from_principal(principal)
    return await governance_service.get_policy(
        db_session,
        organization_id=organization_id,
    )


@router.patch("/governance", response_model=GovernancePolicyUpdateResponse)
async def update_governance_policy(
    payload: GovernancePolicyUpdateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GovernancePolicyUpdateResponse:
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)

    try:
        response = await governance_service.update_policy(
            db_session,
            organization_id=organization_id,
            updated_by_user_id=user_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    audit_recorded = False
    if response.changed_fields:
        audit_recorded = await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="admin.governance.policy.updated",
            resource_type="organization_governance_policy",
            request_id=request_id,
            metadata={
                "changed_fields": response.changed_fields,
                "status_code": status.HTTP_200_OK,
                "allowed_tool_count": len(response.policy.allowed_tool_names),
                "side_effect_tools_allowed": response.policy.allow_side_effect_tools,
                "external_mcp_server_count": len(response.policy.external_mcp_servers),
                "updated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
    await db_session.commit()

    return response.model_copy(
        update={"audit_recorded": audit_recorded if response.changed_fields else False}
    )
