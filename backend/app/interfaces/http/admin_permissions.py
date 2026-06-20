from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.permissions.repositories.permissions import PermissionsRepository
from app.domains.permissions.schemas.permissions import (
    CreateResourceAccessRequest,
    ResourceAccessEntryResponse,
    ResourceAccessListResponse,
    RoleMatrixResponse,
    UpdateRolePermissionsRequest,
    UpdateRolePermissionsResponse,
)
from app.domains.permissions.services.permissions_service import (
    PermissionsService,
    check_role_permission_safety,
)
from app.domains.roles.schemas.roles import builtin_roles_response
from app.models.permissions import PERMISSION_CATALOG, ROLE_PERMISSIONS, PermissionType

router = APIRouter(prefix="/admin/permissions", tags=["permissions"])

_repo = PermissionsRepository()
_service = PermissionsService()
_audit = AuditLogService()
_logger = get_logger("events.permissions")

_ALL_PERMISSION_KEYS = [entry["permission"] for entry in PERMISSION_CATALOG]
_BUILTIN_ROLES = {r["role"] for r in [br.model_dump() for br in builtin_roles_response()]}


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No active organization context"
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid organization context"
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid principal context"
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


# ── Role matrix ────────────────────────────────────────────────────────────────


@router.get("/role-matrix", response_model=RoleMatrixResponse)
async def get_role_matrix(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_view)),
    ],
) -> RoleMatrixResponse:
    """Return all builtin roles with their current effective permission sets."""
    roles = []
    for br in builtin_roles_response():
        canonical = ROLE_PERMISSIONS.get(br.role, frozenset())
        entry = _service.build_role_matrix_entry(
            role_name=br.role,
            effective_permissions=canonical,
            is_builtin=True,
        )
        roles.append(entry)
    return RoleMatrixResponse(roles=roles, all_permissions=sorted(_ALL_PERMISSION_KEYS))


@router.patch("/role-matrix/{role_name}", response_model=UpdateRolePermissionsResponse)
async def update_role_permissions(
    request: Request,
    role_name: str,
    payload: UpdateRolePermissionsRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> UpdateRolePermissionsResponse:
    """Update the effective permissions for a builtin role (owner-only for owner role)."""
    if role_name not in _BUILTIN_ROLES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if role_name == "owner" and principal.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners can modify the owner role permissions",
        )

    # Validate all permissions are known
    unknown = [
        p for p in payload.permissions if p not in {e["permission"] for e in PERMISSION_CATALOG}
    ]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown permissions: {unknown}",
        )

    # Safety: build current state of all roles and check proposed change
    all_current: dict[str, frozenset[str]] = {
        r: ROLE_PERMISSIONS.get(r, frozenset()) for r in _BUILTIN_ROLES
    }
    error = check_role_permission_safety(
        role_name, payload.permissions, all_roles_current=all_current
    )
    if error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error)

    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    await _audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="permissions.role_matrix.updated",
        resource_type="role",
        resource_id=None,
        request_id=request_id,
        metadata={
            "role_name": role_name,
            "permission_count": len(payload.permissions),
            "status_code": status.HTTP_200_OK,
        },
    )
    await db.commit()

    _logger.info(
        "permissions.role_matrix.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        role_name=role_name,
    )

    return _service.build_update_response(role_name, list(set(payload.permissions)))


# ── Resource access grants ─────────────────────────────────────────────────────


@router.get("/resource-grants", response_model=ResourceAccessListResponse)
async def list_resource_grants(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    resource_type: str | None = Query(default=None),
    grant_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ResourceAccessListResponse:
    organization_id = _org_id(principal)
    grants, total = await _repo.list_grants(
        db,
        organization_id=organization_id,
        resource_type=resource_type,
        status=grant_status,
        page=page,
        page_size=page_size,
    )
    return ResourceAccessListResponse(
        items=[_service.grant_to_response(g) for g in grants],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/resource-grants",
    response_model=ResourceAccessEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_resource_grant(
    request: Request,
    payload: CreateResourceAccessRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ResourceAccessEntryResponse:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    grant = await _repo.create_grant(
        db,
        organization_id=organization_id,
        created_by_user_id=actor_id,
        principal_type=payload.principal_type,
        principal_value=payload.principal_value,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        action=payload.action,
        expires_at=payload.expires_at,
        reason=payload.reason,
    )
    await _audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="permissions.resource_grant.created",
        resource_type="resource_grant",
        resource_id=grant.id,
        request_id=request_id,
        metadata={
            "principal_type": payload.principal_type,
            "principal_value": payload.principal_value,
            "resource_type": payload.resource_type,
            "resource_id": payload.resource_id,
            "action": payload.action,
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await db.commit()

    _logger.info(
        "permissions.resource_grant.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        grant_id=str(grant.id),
    )
    return _service.grant_to_response(grant)


@router.delete("/resource-grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_resource_grant(
    request: Request,
    grant_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(grant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found"
        ) from exc

    grant = await _repo.get_grant(db, grant_id=parsed_id, organization_id=organization_id)
    if grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found")

    await _repo.revoke_grant(db, grant=grant)
    await _audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="permissions.resource_grant.revoked",
        resource_type="resource_grant",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={
            "principal_value": grant.principal_value,
            "resource_type": grant.resource_type,
            "status_code": status.HTTP_204_NO_CONTENT,
        },
    )
    await db.commit()

    _logger.info(
        "permissions.resource_grant.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        grant_id=grant_id,
    )


# ── Resource access denies ─────────────────────────────────────────────────────


@router.get("/resource-denies", response_model=ResourceAccessListResponse)
async def list_resource_denies(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    resource_type: str | None = Query(default=None),
    deny_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ResourceAccessListResponse:
    organization_id = _org_id(principal)
    denies, total = await _repo.list_denies(
        db,
        organization_id=organization_id,
        resource_type=resource_type,
        status=deny_status,
        page=page,
        page_size=page_size,
    )
    return ResourceAccessListResponse(
        items=[_service.deny_to_response(d) for d in denies],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/resource-denies",
    response_model=ResourceAccessEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_resource_deny(
    request: Request,
    payload: CreateResourceAccessRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ResourceAccessEntryResponse:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    deny = await _repo.create_deny(
        db,
        organization_id=organization_id,
        created_by_user_id=actor_id,
        principal_type=payload.principal_type,
        principal_value=payload.principal_value,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        action=payload.action,
        expires_at=payload.expires_at,
        reason=payload.reason,
    )
    await _audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="permissions.resource_deny.created",
        resource_type="resource_deny",
        resource_id=deny.id,
        request_id=request_id,
        metadata={
            "principal_type": payload.principal_type,
            "principal_value": payload.principal_value,
            "resource_type": payload.resource_type,
            "resource_id": payload.resource_id,
            "action": payload.action,
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await db.commit()

    _logger.info(
        "permissions.resource_deny.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        deny_id=str(deny.id),
    )
    return _service.deny_to_response(deny)


@router.delete("/resource-denies/{deny_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_resource_deny(
    request: Request,
    deny_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_manage)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(deny_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deny not found") from exc

    deny = await _repo.get_deny(db, deny_id=parsed_id, organization_id=organization_id)
    if deny is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deny not found")

    await _repo.revoke_deny(db, deny=deny)
    await _audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="permissions.resource_deny.revoked",
        resource_type="resource_deny",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={
            "principal_value": deny.principal_value,
            "resource_type": deny.resource_type,
            "status_code": status.HTTP_204_NO_CONTENT,
        },
    )
    await db.commit()

    _logger.info(
        "permissions.resource_deny.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        deny_id=deny_id,
    )
