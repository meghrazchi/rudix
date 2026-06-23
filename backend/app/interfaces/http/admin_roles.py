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
from app.domains.roles.repositories.roles import RolesRepository
from app.domains.roles.schemas.roles import (
    CreateCustomRoleRequest,
    CustomRoleResponse,
    PermissionCatalogResponse,
    PermissionEntry,
    RoleListResponse,
    UpdateCustomRoleRequest,
    builtin_roles_response,
)
from app.domains.roles.services.roles_service import RolesService
from app.models.permissions import PERMISSION_CATALOG, PermissionType

router = APIRouter(prefix="/admin/roles", tags=["roles"])
roles_repository = RolesRepository()
roles_service = RolesService()
audit_log_service = AuditLogService()
roles_logger = get_logger("events.roles")


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


@router.get("/permissions", response_model=PermissionCatalogResponse)
async def list_permissions(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_view)),
    ],
) -> PermissionCatalogResponse:
    items = [
        PermissionEntry(
            permission=entry["permission"],
            category=entry["category"],
            description=entry["description"],
        )
        for entry in PERMISSION_CATALOG
    ]
    return PermissionCatalogResponse(items=items, total=len(items))


@router.get("", response_model=RoleListResponse)
async def list_roles(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_view)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RoleListResponse:
    organization_id = _org_id(principal)
    custom_roles = await roles_repository.list_custom_roles(
        db_session, organization_id=organization_id
    )
    return RoleListResponse(
        builtin_roles=builtin_roles_response(),
        custom_roles=[roles_service.to_custom_role_response(r) for r in custom_roles],
    )


@router.post("", response_model=CustomRoleResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_role(
    request: Request,
    payload: CreateCustomRoleRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomRoleResponse:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    existing = await roles_repository.get_custom_role_by_name(
        db_session,
        name=payload.name,
        organization_id=organization_id,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A custom role with this name already exists",
        )

    role = await roles_repository.create_custom_role(
        db_session,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        base_role=payload.base_role,
        permissions=payload.permissions,
        created_by_id=actor_id,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="roles.custom_role.created",
        resource_type="custom_role",
        resource_id=role.id,
        request_id=request_id,
        metadata={
            "name": role.name,
            "base_role": role.base_role,
            "permission_count": len(payload.permissions),
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await db_session.commit()

    roles_logger.info(
        "roles.custom_role.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        role_id=str(role.id),
        name=role.name,
    )
    return roles_service.to_custom_role_response(role)


@router.get("/{role_id}", response_model=CustomRoleResponse)
async def get_custom_role(
    role_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_view)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomRoleResponse:
    organization_id = _org_id(principal)
    try:
        parsed_id = UUID(role_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found") from exc

    role = await roles_repository.get_custom_role(
        db_session, role_id=parsed_id, organization_id=organization_id
    )
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return roles_service.to_custom_role_response(role)


@router.patch("/{role_id}", response_model=CustomRoleResponse)
async def update_custom_role(
    request: Request,
    role_id: str,
    payload: UpdateCustomRoleRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomRoleResponse:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(role_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found") from exc

    role = await roles_repository.get_custom_role(
        db_session, role_id=parsed_id, organization_id=organization_id
    )
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    if payload.name is not None and payload.name != role.name:
        conflict = await roles_repository.get_custom_role_by_name(
            db_session, name=payload.name, organization_id=organization_id
        )
        if conflict is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A custom role with this name already exists",
            )

    role = await roles_repository.update_custom_role(
        db_session,
        role=role,
        name=payload.name,
        description=payload.description,
        base_role=payload.base_role,
        permissions=payload.permissions,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="roles.custom_role.updated",
        resource_type="custom_role",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={
            "name": role.name,
            "status_code": status.HTTP_200_OK,
        },
    )
    await db_session.commit()
    await db_session.refresh(role)
    await db_session.refresh(role, attribute_names=["permissions"])

    roles_logger.info(
        "roles.custom_role.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        role_id=str(role.id),
    )
    return roles_service.to_custom_role_response(role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_role(
    request: Request,
    role_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.roles_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(role_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found") from exc

    role = await roles_repository.get_custom_role(
        db_session, role_id=parsed_id, organization_id=organization_id
    )
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    await roles_repository.delete_custom_role(db_session, role=role)
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="roles.custom_role.deleted",
        resource_type="custom_role",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": role.name, "status_code": status.HTTP_204_NO_CONTENT},
    )
    await db_session.commit()

    roles_logger.info(
        "roles.custom_role.deleted",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        role_id=role_id,
    )
