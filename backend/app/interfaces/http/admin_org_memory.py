"""HTTP interface — admin org workflow memory review and management (F343)."""

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
from app.domains.memory.schemas.memory import WorkflowListResponse, WorkflowResponse
from app.domains.memory.services.memory_service import OrgWorkflowService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/memory", tags=["admin-memory"])

_wf_svc = OrgWorkflowService()
_audit = AuditLogService()

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


@router.get("/workflows", response_model=WorkflowListResponse)
async def admin_list_workflows(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    workflow_type: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowListResponse:
    _require_feature_enabled()
    org_id = _org_id(principal)
    return await _wf_svc.admin_list(
        db,
        organization_id=org_id,
        status=status_filter,
        workflow_type=workflow_type,
        query=query,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/workflows/{workflow_id}/archive",
    response_model=WorkflowResponse,
)
async def admin_archive_workflow(
    workflow_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowResponse:
    _require_feature_enabled()
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    wf_uuid = _parse_uuid(workflow_id, "Workflow")

    archived = await _wf_svc.admin_archive(db, workflow_id=wf_uuid, organization_id=org_id)
    if not archived:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    # Re-fetch the archived record for the response.
    from app.domains.memory.repositories.memory import OrgWorkflowRepository
    from app.domains.memory.services.memory_service import _workflow_to_response

    wf = await OrgWorkflowRepository().get(db, workflow_id=wf_uuid, organization_id=org_id)
    if wf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found after archive"
        )

    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="org_workflow.archived",
        resource_type="org_workflow",
        resource_id=wf_uuid,
        request_id=_request_id(request),
        metadata={"name": wf.name},
    )
    await db.commit()
    return _workflow_to_response(wf)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_workflow(
    workflow_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    _require_feature_enabled()
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    wf_uuid = _parse_uuid(workflow_id, "Workflow")

    # Capture name before deletion for audit.
    from app.domains.memory.repositories.memory import OrgWorkflowRepository

    wf = await OrgWorkflowRepository().get(db, workflow_id=wf_uuid, organization_id=org_id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    name = wf.name

    deleted = await _wf_svc.admin_delete(db, workflow_id=wf_uuid, organization_id=org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="org_workflow.deleted",
        resource_type="org_workflow",
        resource_id=wf_uuid,
        request_id=_request_id(request),
        metadata={"name": name},
    )
    await db.commit()
