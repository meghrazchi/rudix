from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin import audit_events
from app.domains.admin.schemas.feature_flags import (
    ALL_FLAG_NAMES,
    FeatureFlagDeleteResponse,
    FeatureFlagSetRequest,
    FeatureFlagSetResponse,
    FeatureFlagsResponse,
)
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.feature_flag_service import FeatureFlagService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin", tags=["admin"])
_audit_service = AuditLogService()
_feature_flag_service = FeatureFlagService()


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
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


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal user context is invalid",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _validate_flag_name(flag_name: str) -> None:
    if flag_name not in ALL_FLAG_NAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown feature flag: {flag_name!r}",
        )


@router.get("/feature-flags", response_model=FeatureFlagsResponse)
async def list_feature_flags(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeatureFlagsResponse:
    organization_id = _org_id(principal)
    return await _feature_flag_service.list_flags(db_session, organization_id=organization_id)


@router.put(
    "/feature-flags/{flag_name}",
    response_model=FeatureFlagSetResponse,
    status_code=status.HTTP_200_OK,
)
async def set_feature_flag(
    flag_name: str,
    payload: FeatureFlagSetRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeatureFlagSetResponse:
    _validate_flag_name(flag_name)
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    try:
        result = await _feature_flag_service.set_flag(
            db_session,
            organization_id=organization_id,
            flag_name=flag_name,
            enabled=payload.enabled,
            reason=payload.reason,
            overridden_by_user_id=user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action=audit_events.FEATURE_FLAG_OVERRIDE_SET,
        resource_type="feature_flag",
        resource_id=flag_name,
        request_id=_request_id(request),
        metadata={
            "flag_name": flag_name,
            "enabled": payload.enabled,
            "reason": payload.reason,
        },
    )
    return result


@router.delete(
    "/feature-flags/{flag_name}",
    response_model=FeatureFlagDeleteResponse,
)
async def clear_feature_flag(
    flag_name: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeatureFlagDeleteResponse:
    _validate_flag_name(flag_name)
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    try:
        result = await _feature_flag_service.clear_flag(
            db_session,
            organization_id=organization_id,
            flag_name=flag_name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action=audit_events.FEATURE_FLAG_OVERRIDE_CLEARED,
        resource_type="feature_flag",
        resource_id=flag_name,
        request_id=_request_id(request),
        metadata={"flag_name": flag_name},
    )
    return result
