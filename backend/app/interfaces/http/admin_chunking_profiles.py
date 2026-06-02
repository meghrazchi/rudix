from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.admin.schemas.chunking_profiles import (
    ChunkingProfileCreateRequest,
    ChunkingProfileListResponse,
    ChunkingProfilePreviewRequest,
    ChunkingProfilePreviewResponse,
    ChunkingProfileResponse,
    ChunkingProfileUpdateRequest,
    StrategyCatalogResponse,
)
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.chunking_profile_service import ChunkingProfileService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/chunking-profiles", tags=["admin", "chunking-profiles"])

_service = ChunkingProfileService()
_audit_log_service = AuditLogService()


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


def _require_feature_enabled() -> None:
    if not settings.feature_enable_chunking_profiles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chunking profiles feature is not enabled for this deployment",
        )


@router.get("/strategies", response_model=StrategyCatalogResponse)
async def list_chunking_strategies(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> StrategyCatalogResponse:
    """List all available chunking strategies and the system default profile config."""
    return _service.get_strategy_catalog()


@router.get("", response_model=ChunkingProfileListResponse)
async def list_chunking_profiles(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChunkingProfileListResponse:
    _require_feature_enabled()
    organization_id = _organization_id_from_principal(principal)
    return await _service.list_profiles(db_session, organization_id=organization_id)


@router.post("", response_model=ChunkingProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_chunking_profile(
    payload: ChunkingProfileCreateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChunkingProfileResponse:
    _require_feature_enabled()
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)

    response = await _service.create_profile(
        db_session,
        organization_id=organization_id,
        created_by_user_id=user_id,
        payload=payload,
    )
    await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.chunking_profile.created",
        resource_type="organization_chunking_profile",
        resource_id=response.profile_id,
        request_id=request_id,
        metadata={
            "profile_slug": response.slug,
            "strategy": response.config.strategy,
            "is_default": response.is_default,
            "status_code": status.HTTP_201_CREATED,
            "created_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    await db_session.commit()
    return response


@router.get("/{profile_id}", response_model=ChunkingProfileResponse)
async def get_chunking_profile(
    profile_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChunkingProfileResponse:
    _require_feature_enabled()
    organization_id = _organization_id_from_principal(principal)
    try:
        pid = UUID(profile_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="profile_id must be a valid UUID",
        ) from exc
    return await _service.get_profile(db_session, profile_id=pid, organization_id=organization_id)


@router.put("/{profile_id}", response_model=ChunkingProfileResponse)
async def update_chunking_profile(
    profile_id: str,
    payload: ChunkingProfileUpdateRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChunkingProfileResponse:
    _require_feature_enabled()
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)

    try:
        pid = UUID(profile_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="profile_id must be a valid UUID",
        ) from exc

    response = await _service.update_profile(
        db_session,
        profile_id=pid,
        organization_id=organization_id,
        updated_by_user_id=user_id,
        payload=payload,
    )
    await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.chunking_profile.updated",
        resource_type="organization_chunking_profile",
        resource_id=profile_id,
        request_id=request_id,
        metadata={
            "profile_slug": response.slug,
            "strategy": response.config.strategy,
            "is_default": response.is_default,
            "status_code": status.HTTP_200_OK,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    await db_session.commit()
    return response


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chunking_profile(
    profile_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    _require_feature_enabled()
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)

    try:
        pid = UUID(profile_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="profile_id must be a valid UUID",
        ) from exc

    await _service.delete_profile(db_session, profile_id=pid, organization_id=organization_id)
    await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.chunking_profile.deleted",
        resource_type="organization_chunking_profile",
        resource_id=profile_id,
        request_id=request_id,
        metadata={
            "status_code": status.HTTP_204_NO_CONTENT,
            "deleted_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    await db_session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{profile_id}/set-default", response_model=ChunkingProfileResponse)
async def set_default_chunking_profile(
    profile_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChunkingProfileResponse:
    _require_feature_enabled()
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)

    try:
        pid = UUID(profile_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="profile_id must be a valid UUID",
        ) from exc

    response = await _service.set_default(
        db_session,
        profile_id=pid,
        organization_id=organization_id,
        updated_by_user_id=user_id,
    )
    await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.chunking_profile.default_set",
        resource_type="organization_chunking_profile",
        resource_id=profile_id,
        request_id=request_id,
        metadata={
            "profile_slug": response.slug,
            "strategy": response.config.strategy,
            "status_code": status.HTTP_200_OK,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    await db_session.commit()
    return response


@router.post("/preview", response_model=ChunkingProfilePreviewResponse)
async def preview_chunking_profile(
    payload: ChunkingProfilePreviewRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> ChunkingProfilePreviewResponse:
    """Test a chunking configuration against sample text. Never returns raw document text."""
    return await _service.preview(payload)
