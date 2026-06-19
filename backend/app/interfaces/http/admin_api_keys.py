from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.api_keys.repositories.api_keys import ApiKeysRepository
from app.domains.api_keys.schemas.api_keys import (
    ApiKeyCreatedResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    CreateApiKeyRequest,
    UpdateApiKeyRequest,
)
from app.domains.api_keys.services.api_keys_service import ApiKeysService
from app.domains.quota.schemas.quota_schemas import QuotaType
from app.domains.quota.services.plan_enforcement_service import plan_enforcement_service
from app.models.permissions import PermissionType

router = APIRouter(prefix="/admin/api-keys", tags=["api_keys"])
api_keys_repository = ApiKeysRepository()
api_keys_service = ApiKeysService()
audit_log_service = AuditLogService()
logger = get_logger("events.api_keys")


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid organization context",
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid principal context",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.api_keys_list)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyListResponse:
    organization_id = _org_id(principal)
    keys = await api_keys_repository.list_api_keys(db_session, organization_id=organization_id)
    items = [api_keys_service.to_api_key_response(k) for k in keys]
    return ApiKeyListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    request: Request,
    payload: CreateApiKeyRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.api_keys_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyCreatedResponse:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)
    await plan_enforcement_service.ensure_within_limit(
        db_session,
        organization_id=organization_id,
        quota_type=QuotaType.api_calls,
        requested_amount=1,
        resource="API key operations",
        guidance="Wait a moment and retry or upgrade your plan.",
    )

    raw_key = ApiKeysService.generate_raw_key()
    key_hash = ApiKeysService.hash_key(raw_key)
    key_prefix = ApiKeysService.key_prefix(raw_key)

    api_key = await api_keys_repository.create_api_key(
        db_session,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
        created_by_id=actor_id,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="api_keys.key.created",
        resource_type="api_key",
        resource_id=api_key.id,
        request_id=request_id,
        metadata={
            "name": api_key.name,
            "scopes": api_key.scopes,
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await plan_enforcement_service.record_usage(
        db_session,
        organization_id=organization_id,
        quota_type=QuotaType.api_calls,
        amount=1,
    )
    await db_session.commit()

    logger.info(
        "api_keys.key.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        key_id=str(api_key.id),
        name=api_key.name,
    )
    return api_keys_service.to_api_key_created_response(api_key, raw_key)


@router.get("/{key_id}", response_model=ApiKeyResponse)
async def get_api_key(
    key_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.api_keys_list)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyResponse:
    organization_id = _org_id(principal)
    try:
        parsed_id = UUID(key_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        ) from exc

    api_key = await api_keys_repository.get_api_key(
        db_session, key_id=parsed_id, organization_id=organization_id
    )
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return api_keys_service.to_api_key_response(api_key)


@router.patch("/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    request: Request,
    key_id: str,
    payload: UpdateApiKeyRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.api_keys_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyResponse:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)
    await plan_enforcement_service.ensure_within_limit(
        db_session,
        organization_id=organization_id,
        quota_type=QuotaType.api_calls,
        requested_amount=1,
        resource="API key operations",
        guidance="Wait a moment and retry or upgrade your plan.",
    )

    try:
        parsed_id = UUID(key_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        ) from exc

    api_key = await api_keys_repository.get_api_key(
        db_session, key_id=parsed_id, organization_id=organization_id
    )
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    if api_key.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot update a revoked key"
        )

    api_key = await api_keys_repository.update_api_key(
        db_session,
        api_key=api_key,
        name=payload.name,
        description=payload.description,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="api_keys.key.updated",
        resource_type="api_key",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": api_key.name, "status_code": status.HTTP_200_OK},
    )
    await db_session.commit()
    await db_session.refresh(api_key)

    logger.info(
        "api_keys.key.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        key_id=key_id,
    )
    return api_keys_service.to_api_key_response(api_key)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    request: Request,
    key_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.api_keys_revoke)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(key_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        ) from exc

    api_key = await api_keys_repository.get_api_key(
        db_session, key_id=parsed_id, organization_id=organization_id
    )
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    if api_key.status == "revoked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Key is already revoked")

    await api_keys_repository.revoke_api_key(db_session, api_key=api_key)
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="api_keys.key.revoked",
        resource_type="api_key",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": api_key.name, "status_code": status.HTTP_204_NO_CONTENT},
    )
    await db_session.commit()

    logger.info(
        "api_keys.key.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        key_id=key_id,
    )


@router.post(
    "/{key_id}/rotate",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_api_key(
    request: Request,
    key_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.api_keys_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyCreatedResponse:
    """Revoke the existing key and issue a new one with the same name and scopes."""
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(key_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        ) from exc

    old_key = await api_keys_repository.get_api_key(
        db_session, key_id=parsed_id, organization_id=organization_id
    )
    if old_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    if old_key.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot rotate a revoked key"
        )

    await api_keys_repository.revoke_api_key(db_session, api_key=old_key)

    raw_key = ApiKeysService.generate_raw_key()
    key_hash = ApiKeysService.hash_key(raw_key)
    key_prefix = ApiKeysService.key_prefix(raw_key)

    new_key = await api_keys_repository.create_api_key(
        db_session,
        organization_id=organization_id,
        name=old_key.name,
        description=old_key.description,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=old_key.scopes if isinstance(old_key.scopes, list) else [],
        expires_at=old_key.expires_at,
        created_by_id=actor_id,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="api_keys.key.rotated",
        resource_type="api_key",
        resource_id=new_key.id,
        request_id=request_id,
        metadata={
            "old_key_id": str(parsed_id),
            "name": new_key.name,
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await plan_enforcement_service.record_usage(
        db_session,
        organization_id=organization_id,
        quota_type=QuotaType.api_calls,
        amount=1,
    )
    await db_session.commit()
    await db_session.refresh(new_key)

    logger.info(
        "api_keys.key.rotated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        old_key_id=key_id,
        new_key_id=str(new_key.id),
    )
    return api_keys_service.to_api_key_created_response(new_key, raw_key)
