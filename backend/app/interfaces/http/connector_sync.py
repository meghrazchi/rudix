"""HTTP API for connector sync job and run management."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.connectors.schemas.sync import (
    CreateSyncJobRequest,
    ForceFullResyncResponse,
    ResolveConflictRequest,
    SyncConflictResponse,
    SyncConflictsListResponse,
    SyncJobResponse,
    SyncJobsListResponse,
    SyncRunResponse,
    SyncRunsListResponse,
    TriggerSyncNowResponse,
    UpdateSyncJobStatusRequest,
)
from app.domains.connectors.services.connector_service import (
    ConnectorPlatformDisabledError,
    ensure_connector_platform_enabled,
)
from app.domains.connectors.services.permission_review_service import PermissionReviewService
from app.domains.connectors.services.sync_engine import ConnectorSyncEngine, SyncEngineError
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun, SyncConflict
from app.models.enums import ConnectorSyncJobStatus, OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/connectors", tags=["connectors"])

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


def _engine() -> ConnectorSyncEngine:
    return ConnectorSyncEngine()


def _require_connector_platform_enabled() -> None:
    try:
        ensure_connector_platform_enabled()
    except ConnectorPlatformDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


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
            detail="Invalid user context",
        ) from exc


def _job_response(job: ConnectorSyncJob) -> SyncJobResponse:
    return SyncJobResponse(
        id=str(job.id),
        organization_id=str(job.organization_id),
        connection_id=str(job.connection_id),
        external_source_id=str(job.external_source_id) if job.external_source_id else None,
        collection_id=str(job.collection_id) if job.collection_id else None,
        name=job.name,
        status=job.status,
        schedule=job.schedule_json or {},
        last_run_at=job.last_run_at.isoformat() if job.last_run_at else None,
        error_message=job.error_message,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


def _run_response(run: ConnectorSyncRun) -> SyncRunResponse:
    return SyncRunResponse(
        id=str(run.id),
        organization_id=str(run.organization_id),
        sync_job_id=str(run.sync_job_id),
        connection_id=str(run.connection_id),
        external_source_id=str(run.external_source_id) if run.external_source_id else None,
        status=run.status,
        trigger_type=run.trigger_type,
        sync_version=run.sync_version,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        items_seen=run.items_seen,
        items_upserted=run.items_upserted,
        items_deleted=run.items_deleted,
        cursor_before=run.cursor_before_json or {},
        cursor_after=run.cursor_after_json or {},
        error_message=run.error_message,
        error_details=run.error_details_json or {},
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Sync jobs
# ---------------------------------------------------------------------------


@router.post(
    "/{connection_id}/sync-jobs",
    response_model=SyncJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sync_job(
    connection_id: UUID,
    payload: CreateSyncJobRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.connector))],
    __: Annotated[None, Depends(_require_connector_platform_enabled)],
) -> SyncJobResponse:
    org_id = _org_id(principal)
    try:
        job = await _engine().create_sync_job(
            db_session,
            organization_id=org_id,
            connection_id=connection_id,
            name=payload.name,
            user_id=_user_id(principal),
            external_source_id=(
                UUID(payload.external_source_id) if payload.external_source_id else None
            ),
            collection_id=(UUID(payload.collection_id) if payload.collection_id else None),
            schedule=payload.schedule,
        )
    except SyncEngineError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await db_session.commit()
    return _job_response(job)


@router.get("/{connection_id}/sync-jobs", response_model=SyncJobsListResponse)
async def list_sync_jobs(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SyncJobsListResponse:
    org_id = _org_id(principal)
    jobs = await _engine().list_sync_jobs(
        db_session, organization_id=org_id, connection_id=connection_id
    )
    return SyncJobsListResponse(
        items=[_job_response(j) for j in jobs],
        total=len(jobs),
    )


@router.get("/{connection_id}/sync-jobs/{job_id}", response_model=SyncJobResponse)
async def get_sync_job(
    connection_id: UUID,
    job_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SyncJobResponse:
    org_id = _org_id(principal)
    job = await _engine().get_sync_job(db_session, organization_id=org_id, job_id=job_id)
    if job is None or job.connection_id != connection_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sync job not found")
    return _job_response(job)


@router.patch("/{connection_id}/sync-jobs/{job_id}", response_model=SyncJobResponse)
async def update_sync_job_status(
    connection_id: UUID,
    job_id: UUID,
    payload: UpdateSyncJobStatusRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.connector))],
    __: Annotated[None, Depends(_require_connector_platform_enabled)],
) -> SyncJobResponse:
    org_id = _org_id(principal)
    try:
        new_status = ConnectorSyncJobStatus(payload.status)
        job = await _engine().update_sync_job_status(
            db_session,
            organization_id=org_id,
            job_id=job_id,
            status=new_status,
            user_id=_user_id(principal),
        )
    except SyncEngineError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if job.connection_id != connection_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sync job not found")
    await db_session.commit()
    return _job_response(job)


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------


@router.post("/{connection_id}/sync/now", response_model=TriggerSyncNowResponse)
async def trigger_sync_now(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.connector))],
    __: Annotated[None, Depends(_require_connector_platform_enabled)],
    job_id: Annotated[UUID | None, Query()] = None,
) -> TriggerSyncNowResponse:
    org_id = _org_id(principal)

    # Block sync until permissions have been explicitly reviewed and confirmed.
    review_confirmed = await PermissionReviewService().is_confirmed(
        db_session,
        organization_id=org_id,
        connection_id=connection_id,
    )
    if not review_confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Permission review required. "
                "An admin must review and confirm the connector permission scope "
                "before indexing can begin."
            ),
        )

    try:
        run = await _engine().trigger_manual_sync(
            db_session,
            organization_id=org_id,
            connection_id=connection_id,
            job_id=job_id,
            user_id=_user_id(principal),
        )
    except SyncEngineError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db_session.commit()

    celery_app.send_task(
        "connectors.sync.run",
        kwargs={
            "sync_run_id": str(run.id),
            "organization_id": str(org_id),
        },
    )
    return TriggerSyncNowResponse(
        sync_run_id=str(run.id),
        status=run.status,
        message="Sync queued",
    )


@router.post("/sync-runs/{run_id}/retry", response_model=TriggerSyncNowResponse)
async def retry_sync_run(
    run_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.connector))],
    __: Annotated[None, Depends(_require_connector_platform_enabled)],
) -> TriggerSyncNowResponse:
    org_id = _org_id(principal)
    try:
        run = await _engine().retry_failed_sync(
            db_session,
            organization_id=org_id,
            run_id=run_id,
            user_id=_user_id(principal),
        )
    except SyncEngineError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db_session.commit()

    celery_app.send_task(
        "connectors.sync.run",
        kwargs={
            "sync_run_id": str(run.id),
            "organization_id": str(org_id),
        },
    )
    return TriggerSyncNowResponse(
        sync_run_id=str(run.id),
        status=run.status,
        message="Sync retried",
    )


# ---------------------------------------------------------------------------
# Sync runs
# ---------------------------------------------------------------------------


@router.get("/{connection_id}/sync-runs", response_model=SyncRunsListResponse)
async def list_sync_runs(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=20, ge=1, le=100),
) -> SyncRunsListResponse:
    org_id = _org_id(principal)
    runs = await _engine().list_sync_runs(
        db_session,
        organization_id=org_id,
        connection_id=connection_id,
        limit=limit,
    )
    return SyncRunsListResponse(
        items=[_run_response(r) for r in runs],
        total=len(runs),
    )


@router.get("/sync-runs/{run_id}", response_model=SyncRunResponse)
async def get_sync_run(
    run_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SyncRunResponse:
    org_id = _org_id(principal)
    run = await _engine().get_sync_run(db_session, organization_id=org_id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sync run not found")
    return _run_response(run)


def _conflict_response(conflict: SyncConflict) -> SyncConflictResponse:
    return SyncConflictResponse(
        id=str(conflict.id),
        organization_id=str(conflict.organization_id),
        connection_id=str(conflict.connection_id),
        external_item_id=str(conflict.external_item_id) if conflict.external_item_id else None,
        sync_run_id=str(conflict.sync_run_id) if conflict.sync_run_id else None,
        provider_item_id=conflict.provider_item_id,
        conflict_type=conflict.conflict_type,
        status=conflict.status,
        conflict_detail=conflict.conflict_detail_json or {},
        resolved_by_user_id=(
            str(conflict.resolved_by_user_id) if conflict.resolved_by_user_id else None
        ),
        resolved_at=conflict.resolved_at.isoformat() if conflict.resolved_at else None,
        resolution_strategy=conflict.resolution_strategy,
        created_at=conflict.created_at.isoformat(),
        updated_at=conflict.updated_at.isoformat(),
    )


@router.post("/sync-runs/{run_id}/cancel", response_model=SyncRunResponse)
async def cancel_sync_run(
    run_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.connector))],
    __: Annotated[None, Depends(_require_connector_platform_enabled)],
) -> SyncRunResponse:
    org_id = _org_id(principal)
    try:
        run = await _engine().cancel_run(db_session, organization_id=org_id, run_id=run_id)
    except SyncEngineError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db_session.commit()
    return _run_response(run)


# ---------------------------------------------------------------------------
# Force full resync
# ---------------------------------------------------------------------------


@router.post("/{connection_id}/sync/full", response_model=ForceFullResyncResponse)
async def trigger_full_resync(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.connector))],
    __: Annotated[None, Depends(_require_connector_platform_enabled)],
    job_id: Annotated[UUID | None, Query()] = None,
) -> ForceFullResyncResponse:
    """Clear the sync cursor and start a full re-index from the provider."""
    org_id = _org_id(principal)

    review_confirmed = await PermissionReviewService().is_confirmed(
        db_session,
        organization_id=org_id,
        connection_id=connection_id,
    )
    if not review_confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Permission review required before syncing.",
        )

    try:
        run = await _engine().trigger_full_resync(
            db_session,
            organization_id=org_id,
            connection_id=connection_id,
            job_id=job_id,
            user_id=_user_id(principal),
        )
    except SyncEngineError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db_session.commit()

    celery_app.send_task(
        "connectors.sync.run",
        kwargs={
            "sync_run_id": str(run.id),
            "organization_id": str(org_id),
        },
    )
    return ForceFullResyncResponse(
        sync_run_id=str(run.id),
        status=run.status,
        message="Full resync queued — cursor cleared",
    )


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


@router.get("/{connection_id}/conflicts", response_model=SyncConflictsListResponse)
async def list_sync_conflicts(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    conflict_status: Annotated[str | None, Query(alias="status")] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SyncConflictsListResponse:
    org_id = _org_id(principal)
    from app.domains.connectors.repositories.connectors import ConnectorRepository

    repo = ConnectorRepository()
    conflicts, total = await repo.list_conflicts(
        db_session,
        organization_id=org_id,
        connection_id=connection_id,
        status=conflict_status,
        limit=limit,
        offset=offset,
    )
    return SyncConflictsListResponse(
        items=[_conflict_response(c) for c in conflicts],
        total=total,
    )


@router.post(
    "/{connection_id}/conflicts/{conflict_id}/resolve",
    response_model=SyncConflictResponse,
)
async def resolve_sync_conflict(
    connection_id: UUID,
    conflict_id: UUID,
    payload: ResolveConflictRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SyncConflictResponse:
    org_id = _org_id(principal)
    from app.domains.connectors.audit import ConnectorAuditAction
    from app.domains.connectors.repositories.connectors import ConnectorRepository
    from app.domains.admin.services.audit_service import AuditLogService, sanitize_metadata

    repo = ConnectorRepository()
    conflict = await repo.get_conflict(db_session, organization_id=org_id, conflict_id=conflict_id)
    if conflict is None or conflict.connection_id != connection_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conflict not found")
    if conflict.status != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"conflict is already {conflict.status}",
        )

    conflict = await repo.resolve_conflict(
        db_session,
        conflict=conflict,
        status=payload.resolution,
        resolved_by_user_id=_user_id(principal),
        resolution_strategy=payload.resolution_strategy,
    )
    await AuditLogService().record(
        db_session,
        organization_id=org_id,
        user_id=_user_id(principal),
        action=ConnectorAuditAction.sync_conflict_resolved.value,
        resource_type="sync_conflict",
        resource_id=conflict.id,
        metadata=sanitize_metadata(
            {
                "conflict_type": conflict.conflict_type,
                "resolution": payload.resolution,
                "resolution_strategy": payload.resolution_strategy,
                "connection_id": str(connection_id),
            }
        ),
    )
    await db_session.commit()
    return _conflict_response(conflict)
