"""HTTP interface — org workflow memory and user preferences (F343)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.memory.schemas.memory import (
    CreateWorkflowRequest,
    MemoryPreferenceResponse,
    UpdateWorkflowRequest,
    UpsertMemoryPreferenceRequest,
    WorkflowListResponse,
    WorkflowResponse,
)
from app.domains.memory.services.memory_service import (
    OrgWorkflowService,
    UserMemoryPreferenceService,
)
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/memory", tags=["memory"])

_wf_svc = OrgWorkflowService()
_pref_svc = UserMemoryPreferenceService()
_audit = AuditLogService()

_READ_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
    OrganizationRole.reviewer.value,
    OrganizationRole.developer.value,
)
_WRITE_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.reviewer.value,
    OrganizationRole.developer.value,
)
_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


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
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid user context"
        ) from exc


def _role_name(principal: AuthenticatedPrincipal) -> str:
    return principal.roles[0] if principal.roles else ""


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found"
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _require_feature_enabled() -> None:
    if not settings.feature_enable_org_memory:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization memory is not enabled for this deployment",
        )


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


@router.post(
    "/workflows",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow(
    request: Request,
    payload: CreateWorkflowRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowResponse:
    _require_feature_enabled()
    org_id = _org_id(principal)
    user_id = _user_id(principal)

    try:
        result = await _wf_svc.create(
            db,
            organization_id=org_id,
            created_by_id=user_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="org_workflow.created",
        resource_type="org_workflow",
        resource_id=UUID(result.workflow_id),
        request_id=_request_id(request),
        metadata={"name": result.name, "workflow_type": result.workflow_type},
    )
    await db.commit()
    return result


@router.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    workflow_type: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowListResponse:
    _require_feature_enabled()
    org_id = _org_id(principal)
    return await _wf_svc.list_active(
        db,
        organization_id=org_id,
        user_role=_role_name(principal),
        workflow_type=workflow_type,
        query=query,
        limit=limit,
        offset=offset,
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowResponse:
    _require_feature_enabled()
    org_id = _org_id(principal)
    wf_uuid = _parse_uuid(workflow_id, "Workflow")
    result = await _wf_svc.get(
        db,
        workflow_id=wf_uuid,
        organization_id=org_id,
        user_role=_role_name(principal),
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.patch("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    request: Request,
    payload: UpdateWorkflowRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowResponse:
    _require_feature_enabled()
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    wf_uuid = _parse_uuid(workflow_id, "Workflow")
    is_admin = _role_name(principal) in _ADMIN_ROLES

    try:
        result = await _wf_svc.update(
            db,
            workflow_id=wf_uuid,
            organization_id=org_id,
            requestor_id=user_id,
            requestor_role=_role_name(principal),
            payload=payload,
            is_admin=is_admin,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="org_workflow.updated",
        resource_type="org_workflow",
        resource_id=wf_uuid,
        request_id=_request_id(request),
        metadata={"name": result.name},
    )
    await db.commit()
    return result


@router.post("/workflows/{workflow_id}/increment-use", status_code=status.HTTP_204_NO_CONTENT)
async def increment_workflow_use(
    workflow_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    _require_feature_enabled()
    org_id = _org_id(principal)
    wf_uuid = _parse_uuid(workflow_id, "Workflow")
    found = await _wf_svc.increment_use(db, workflow_id=wf_uuid, organization_id=org_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await db.commit()


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------


@router.get("/preferences", response_model=MemoryPreferenceResponse)
async def get_preferences(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryPreferenceResponse:
    _require_feature_enabled()
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    result = await _pref_svc.get(db, organization_id=org_id, user_id=user_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No preferences saved yet"
        )
    return result


@router.put("/preferences", response_model=MemoryPreferenceResponse)
async def upsert_preferences(
    request: Request,
    payload: UpsertMemoryPreferenceRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemoryPreferenceResponse:
    _require_feature_enabled()
    org_id = _org_id(principal)
    user_id = _user_id(principal)

    try:
        result = await _pref_svc.upsert(
            db,
            organization_id=org_id,
            user_id=user_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await db.commit()
    return result


@router.delete("/preferences", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preferences(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    _require_feature_enabled()
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    deleted = await _pref_svc.delete(db, organization_id=org_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No preferences found")
    await db.commit()
