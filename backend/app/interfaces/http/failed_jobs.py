from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.schemas.failed_jobs import (
    BulkRetryRequest,
    BulkRetryResponse,
    FailedJobAuditEntry,
    FailedJobDetail,
    FailedJobsListResponse,
    FailedJobSummary,
)
from app.models.enums import OrganizationRole
from app.models.failed_job import FailedJob, FailedJobAuditLog
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/admin/failed-jobs", tags=["admin-failed-jobs"])

_PAGE_SIZE_MAX = 100
_PAGE_SIZE_DEFAULT = 25
_SAFE_STATUSES_FOR_RETRY = frozenset({"failed"})
_TERMINAL_STATUSES = frozenset({"resolved", "cancelled"})


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


def _principal_user_id(principal: AuthenticatedPrincipal) -> UUID | None:
    if principal.user_id is None:
        return None
    try:
        return UUID(principal.user_id)
    except ValueError:
        return None


def _job_to_summary(job: FailedJob) -> FailedJobSummary:
    return FailedJobSummary(
        id=job.id,
        organization_id=job.organization_id,
        task_id=job.task_id,
        task_name=job.task_name,
        job_type=job.job_type,
        status=job.status,
        queue_name=job.queue_name,
        error_code=job.error_code,
        attempt_count=job.attempt_count,
        is_retryable=job.is_retryable,
        entity_type=job.entity_type,
        entity_id=job.entity_id,
        last_attempted_at=job.last_attempted_at,
        resolved_at=job.resolved_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _job_to_detail(job: FailedJob) -> FailedJobDetail:
    audit_entries = [
        FailedJobAuditEntry(
            id=entry.id,
            action=entry.action,
            performed_by_id=entry.performed_by_id,
            note=entry.note,
            created_at=entry.created_at,
        )
        for entry in sorted(job.audit_logs, key=lambda e: e.created_at)
    ]
    return FailedJobDetail(
        id=job.id,
        organization_id=job.organization_id,
        task_id=job.task_id,
        task_name=job.task_name,
        job_type=job.job_type,
        status=job.status,
        queue_name=job.queue_name,
        error_code=job.error_code,
        error_message=job.error_message,
        attempt_count=job.attempt_count,
        is_retryable=job.is_retryable,
        entity_type=job.entity_type,
        entity_id=job.entity_id,
        metadata_json=job.metadata_json if isinstance(job.metadata_json, dict) else {},
        last_attempted_at=job.last_attempted_at,
        resolved_at=job.resolved_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        audit_log=audit_entries,
    )


async def _append_audit(
    db: AsyncSession,
    *,
    failed_job_id: UUID,
    organization_id: UUID,
    action: str,
    performed_by_id: UUID | None,
    note: str | None = None,
) -> None:
    entry = FailedJobAuditLog(
        id=uuid4(),
        failed_job_id=failed_job_id,
        organization_id=organization_id,
        action=action,
        performed_by_id=performed_by_id,
        note=note,
        created_at=datetime.now(tz=UTC),
    )
    db.add(entry)


def _dispatch_retry(job: FailedJob) -> None:
    kwargs: dict = {
        "organization_id": str(job.organization_id),
        "job_id": str(job.id),
    }
    if job.entity_id is not None:
        if job.entity_type == "document":
            kwargs["document_id"] = str(job.entity_id)
        elif job.entity_type == "evaluation_run":
            kwargs["evaluation_run_id"] = str(job.entity_id)
    celery_app.send_task(
        job.task_name,
        kwargs=kwargs,
        queue=job.queue_name or "default",
    )


@router.get("", response_model=FailedJobsListResponse)
async def list_failed_jobs(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    job_type: Annotated[str | None, Query(max_length=64)] = None,
    job_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    queue_name: Annotated[str | None, Query(max_length=128)] = None,
    retryable_only: Annotated[bool, Query()] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=_PAGE_SIZE_MAX)] = _PAGE_SIZE_DEFAULT,
) -> FailedJobsListResponse:
    organization_id = _organization_id(principal)

    base = select(FailedJob).where(FailedJob.organization_id == organization_id)
    if job_type is not None:
        base = base.where(FailedJob.job_type == job_type)
    if job_status is not None:
        base = base.where(FailedJob.status == job_status)
    if queue_name is not None:
        base = base.where(FailedJob.queue_name == queue_name)
    if retryable_only:
        base = base.where(FailedJob.is_retryable.is_(True))

    count_stmt = select(func.count()).select_from(base.subquery())
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    items_stmt = (
        base.order_by(FailedJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return FailedJobsListResponse(
        items=[_job_to_summary(j) for j in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{job_id}", response_model=FailedJobDetail)
async def get_failed_job(
    job_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> FailedJobDetail:
    organization_id = _organization_id(principal)
    stmt = (
        select(FailedJob)
        .where(FailedJob.id == job_id, FailedJob.organization_id == organization_id)
        .options(selectinload(FailedJob.audit_logs))
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_to_detail(job)


@router.post("/{job_id}/retry", response_model=FailedJobSummary, status_code=status.HTTP_200_OK)
async def retry_failed_job(
    job_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> FailedJobSummary:
    organization_id = _organization_id(principal)
    user_id = _principal_user_id(principal)

    stmt = select(FailedJob).where(
        FailedJob.id == job_id, FailedJob.organization_id == organization_id
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status not in _SAFE_STATUSES_FOR_RETRY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job in status '{job.status}' cannot be retried. Only 'failed' jobs are eligible.",
        )
    if not job.is_retryable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This job is marked non-retryable. Retrying it could cause duplicate or unsafe operations.",
        )

    now = datetime.now(tz=UTC)
    job.status = "retrying"
    job.updated_at = now
    await _append_audit(
        db,
        failed_job_id=job.id,
        organization_id=organization_id,
        action="retry",
        performed_by_id=user_id,
    )
    await db.flush()

    _dispatch_retry(job)
    await db.commit()
    await db.refresh(job)
    return _job_to_summary(job)


@router.post("/bulk-retry", response_model=BulkRetryResponse, status_code=status.HTTP_200_OK)
async def bulk_retry_failed_jobs(
    body: BulkRetryRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> BulkRetryResponse:
    organization_id = _organization_id(principal)
    user_id = _principal_user_id(principal)

    stmt = select(FailedJob).where(
        FailedJob.id.in_(body.job_ids),
        FailedJob.organization_id == organization_id,
    )
    jobs = list((await db.execute(stmt)).scalars().all())
    found_ids = {j.id for j in jobs}

    queued: list[UUID] = []
    skipped: list[UUID] = []
    skip_reasons: dict[str, str] = {}
    now = datetime.now(tz=UTC)

    for job_id in body.job_ids:
        if job_id not in found_ids:
            skipped.append(job_id)
            skip_reasons[str(job_id)] = "not_found"
            continue

        job = next(j for j in jobs if j.id == job_id)
        if job.status not in _SAFE_STATUSES_FOR_RETRY:
            skipped.append(job_id)
            skip_reasons[str(job_id)] = f"status_{job.status}"
            continue
        if not job.is_retryable:
            skipped.append(job_id)
            skip_reasons[str(job_id)] = "non_retryable"
            continue

        job.status = "retrying"
        job.updated_at = now
        await _append_audit(
            db,
            failed_job_id=job.id,
            organization_id=organization_id,
            action="retry",
            performed_by_id=user_id,
            note="bulk_retry",
        )
        queued.append(job_id)

    await db.flush()
    for job_id in queued:
        job = next(j for j in jobs if j.id == job_id)
        _dispatch_retry(job)

    await db.commit()
    return BulkRetryResponse(queued=queued, skipped=skipped, skip_reasons=skip_reasons)


@router.post("/{job_id}/cancel", response_model=FailedJobSummary, status_code=status.HTTP_200_OK)
async def cancel_failed_job(
    job_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> FailedJobSummary:
    organization_id = _organization_id(principal)
    user_id = _principal_user_id(principal)

    stmt = select(FailedJob).where(
        FailedJob.id == job_id, FailedJob.organization_id == organization_id
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is already in terminal status '{job.status}'.",
        )

    now = datetime.now(tz=UTC)
    job.status = "cancelled"
    job.resolved_at = now
    job.updated_at = now
    await _append_audit(
        db,
        failed_job_id=job.id,
        organization_id=organization_id,
        action="cancel",
        performed_by_id=user_id,
    )
    await db.commit()
    await db.refresh(job)
    return _job_to_summary(job)


@router.post("/{job_id}/resolve", response_model=FailedJobSummary, status_code=status.HTTP_200_OK)
async def resolve_failed_job(
    job_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> FailedJobSummary:
    organization_id = _organization_id(principal)
    user_id = _principal_user_id(principal)

    stmt = select(FailedJob).where(
        FailedJob.id == job_id, FailedJob.organization_id == organization_id
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status == "resolved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job is already resolved.",
        )

    now = datetime.now(tz=UTC)
    job.status = "resolved"
    job.resolved_at = now
    job.updated_at = now
    await _append_audit(
        db,
        failed_job_id=job.id,
        organization_id=organization_id,
        action="mark_resolved",
        performed_by_id=user_id,
    )
    await db.commit()
    await db.refresh(job)
    return _job_to_summary(job)
