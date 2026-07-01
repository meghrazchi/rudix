from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.schemas.portability import (
    WorkspaceExportRequest,
    WorkspaceImportRequest,
    WorkspacePortabilityJobListResponse,
    WorkspacePortabilityJobResponse,
)
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.portability_service import WorkspacePortabilityService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/portability", tags=["admin-portability"])

_service = WorkspacePortabilityService()
_audit = AuditLogService()


def _organization_id(principal: AuthenticatedPrincipal) -> UUID:
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
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid principal context",
        ) from exc


def _request_id(request: Request) -> str | None:
    state_request_id = getattr(request.state, "request_id", None)
    if isinstance(state_request_id, str) and state_request_id.strip():
        return state_request_id
    return request.headers.get("x-request-id")


@router.post("/exports", response_model=WorkspacePortabilityJobResponse, status_code=201)
async def create_workspace_export(
    payload: WorkspaceExportRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkspacePortabilityJobResponse:
    organization_id = _organization_id(principal)
    actor_user_id = _user_id(principal)
    job = await _service.create_export_job(
        db_session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        request=payload,
    )
    await _audit.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="workspace_portability.export.requested",
        resource_type="workspace_portability_job",
        resource_id=job.id,
        request_id=_request_id(request),
        metadata={
            "sections": list(payload.sections),
            "status": job.status,
            "artifact_size_bytes": job.artifact_size_bytes,
            "max_rows_per_section": payload.max_rows_per_section,
        },
    )
    await db_session.commit()
    await db_session.refresh(job)
    return _service.to_response(job)


@router.post("/imports", response_model=WorkspacePortabilityJobResponse, status_code=201)
async def create_workspace_import(
    payload: WorkspaceImportRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkspacePortabilityJobResponse:
    organization_id = _organization_id(principal)
    actor_user_id = _user_id(principal)
    job = await _service.create_import_job(
        db_session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        request=payload,
    )
    await _audit.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="workspace_portability.import.requested",
        resource_type="workspace_portability_job",
        resource_id=job.id,
        request_id=_request_id(request),
        metadata={
            "sections": list(job.requested_sections_json or []),
            "apply": payload.apply,
            "status": job.status,
            "validation_error_count": len(job.validation_errors_json or []),
        },
    )
    await db_session.commit()
    await db_session.refresh(job)
    return _service.to_response(job)


@router.get("/jobs", response_model=WorkspacePortabilityJobListResponse)
async def list_workspace_portability_jobs(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkspacePortabilityJobListResponse:
    organization_id = _organization_id(principal)
    jobs, total = await _service.list_jobs(
        db_session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )
    return WorkspacePortabilityJobListResponse(
        items=[_service.to_response(job) for job in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=WorkspacePortabilityJobResponse)
async def get_workspace_portability_job(
    job_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkspacePortabilityJobResponse:
    organization_id = _organization_id(principal)
    job = await _service.get_job(db_session, organization_id=organization_id, job_id=job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Portability job not found"
        )
    return _service.to_response(job)


@router.get("/jobs/{job_id}/download")
async def download_workspace_portability_artifact(
    job_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    organization_id = _organization_id(principal)
    job = await _service.get_job(db_session, organization_id=organization_id, job_id=job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Portability job not found"
        )
    response = _service.to_response(job)
    if not response.download_available or job.artifact_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Artifact is not available"
        )
    filename = job.artifact_filename or f"rudix-portability-{str(job.id)[:8]}.json"
    return Response(
        content=json.dumps(job.artifact_json, sort_keys=True),
        media_type=job.artifact_mime_type or "application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
