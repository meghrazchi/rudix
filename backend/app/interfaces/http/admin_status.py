from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_principal, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.schemas.incidents import (
    AddIncidentNoteRequest,
    CreateIncidentRequest,
    IncidentDetail,
    IncidentNoteEntry,
    IncidentsListResponse,
    IncidentSummary,
    ServiceStatusBanner,
    ServiceStatusSnapshot,
    UpdateIncidentRequest,
)
from app.models.enums import OrganizationRole
from app.models.failed_job import FailedJob
from app.models.incident import Incident, IncidentNote
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(tags=["admin-status"])

_PAGE_SIZE_MAX = 100
_PAGE_SIZE_DEFAULT = 25
_ACTIVE_STATUSES = frozenset({"investigating", "identified", "monitoring"})
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_RESOLVED_LOOKBACK_HOURS = 24


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


def _user_id(principal: AuthenticatedPrincipal) -> UUID | None:
    if principal.user_id is None:
        return None
    try:
        return UUID(principal.user_id)
    except ValueError:
        return None


def _to_summary(incident: Incident) -> IncidentSummary:
    return IncidentSummary(
        id=incident.id,
        organization_id=incident.organization_id,
        title=incident.title,
        status=incident.status,
        severity=incident.severity,
        affected_services=(
            incident.affected_services if isinstance(incident.affected_services, list) else []
        ),
        message=incident.message,
        is_public=incident.is_public,
        started_at=incident.started_at,
        resolved_at=incident.resolved_at,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )


def _to_detail(incident: Incident) -> IncidentDetail:
    notes = [
        IncidentNoteEntry(
            id=n.id,
            note=n.note,
            status_change=n.status_change,
            created_by_id=n.created_by_id,
            created_at=n.created_at,
        )
        for n in sorted(incident.notes, key=lambda n: n.created_at)
    ]
    return IncidentDetail(**_to_summary(incident).model_dump(), notes=notes)


def _highest_severity(incidents: list[Incident]) -> str | None:
    if not incidents:
        return None
    return min(incidents, key=lambda i: _SEVERITY_ORDER.get(i.severity, 99)).severity


def _build_banner(
    active: list[Incident],
    maintenance: list[Incident],
) -> ServiceStatusBanner:
    has_active = len(active) > 0
    has_maintenance = len(maintenance) > 0
    message: str | None = None
    if has_maintenance:
        message = maintenance[0].message or maintenance[0].title
    elif has_active:
        message = active[0].message or active[0].title
    return ServiceStatusBanner(
        has_active_incident=has_active,
        has_active_maintenance=has_maintenance,
        active_incident_count=len(active),
        banner_message=message,
        highest_severity=_highest_severity(active),
    )


# ---------------------------------------------------------------------------
# GET /admin/status  — full snapshot (admin only)
# ---------------------------------------------------------------------------


@router.get("/admin/status", response_model=ServiceStatusSnapshot)
async def get_status_snapshot(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceStatusSnapshot:
    org_id = _org_id(principal)
    now = datetime.now(tz=UTC)
    lookback = now - timedelta(hours=_RESOLVED_LOOKBACK_HOURS)

    active_stmt = (
        select(Incident)
        .where(
            Incident.organization_id == org_id,
            Incident.status.in_(list(_ACTIVE_STATUSES)),
        )
        .order_by(Incident.started_at.desc())
    )
    active_incidents = list((await db.execute(active_stmt)).scalars().all())

    resolved_stmt = (
        select(Incident)
        .where(
            Incident.organization_id == org_id,
            Incident.status == "resolved",
            Incident.resolved_at >= lookback,
        )
        .order_by(Incident.resolved_at.desc())
        .limit(10)
    )
    recently_resolved = list((await db.execute(resolved_stmt)).scalars().all())

    failed_count_stmt = select(func.count()).select_from(
        select(FailedJob)
        .where(
            FailedJob.organization_id == org_id,
            FailedJob.status == "failed",
        )
        .subquery()
    )
    open_failed = int((await db.execute(failed_count_stmt)).scalar_one() or 0)

    maintenance = [i for i in active_incidents if i.title.lower().startswith("maintenance")]
    non_maintenance = [i for i in active_incidents if i not in maintenance]

    return ServiceStatusSnapshot(
        organization_id=org_id,
        generated_at=now,
        active_incidents=[_to_summary(i) for i in non_maintenance],
        recently_resolved=[_to_summary(i) for i in recently_resolved],
        open_failed_job_count=open_failed,
        banner=_build_banner(non_maintenance, maintenance),
    )


# ---------------------------------------------------------------------------
# GET /status/banner  — public banner check (any authenticated user)
# ---------------------------------------------------------------------------


@router.get("/status/banner", response_model=ServiceStatusBanner)
async def get_status_banner(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceStatusBanner:
    org_id = _org_id(principal)

    stmt = (
        select(Incident)
        .where(
            Incident.organization_id == org_id,
            Incident.status.in_(list(_ACTIVE_STATUSES)),
            Incident.is_public.is_(True),
        )
        .order_by(Incident.started_at.desc())
    )
    active = list((await db.execute(stmt)).scalars().all())

    maintenance = [i for i in active if i.title.lower().startswith("maintenance")]
    non_maintenance = [i for i in active if i not in maintenance]

    return _build_banner(non_maintenance, maintenance)


# ---------------------------------------------------------------------------
# GET /admin/incidents  — list incidents
# ---------------------------------------------------------------------------


@router.get("/admin/incidents", response_model=IncidentsListResponse)
async def list_incidents(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    incident_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    severity: Annotated[str | None, Query(max_length=32)] = None,
    active_only: Annotated[bool, Query()] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=_PAGE_SIZE_MAX)] = _PAGE_SIZE_DEFAULT,
) -> IncidentsListResponse:
    org_id = _org_id(principal)

    base = select(Incident).where(Incident.organization_id == org_id)
    if active_only:
        base = base.where(Incident.status.in_(list(_ACTIVE_STATUSES)))
    elif incident_status is not None:
        base = base.where(Incident.status == incident_status)
    if severity is not None:
        base = base.where(Incident.severity == severity)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    items_stmt = (
        base.order_by(Incident.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = list((await db.execute(items_stmt)).scalars().all())

    return IncidentsListResponse(
        items=[_to_summary(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# POST /admin/incidents  — create incident
# ---------------------------------------------------------------------------


@router.post(
    "/admin/incidents",
    response_model=IncidentDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_incident(
    body: CreateIncidentRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> IncidentDetail:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    now = datetime.now(tz=UTC)

    incident = Incident(
        id=uuid4(),
        organization_id=org_id,
        title=body.title,
        status="investigating",
        severity=body.severity,
        affected_services=body.affected_services,
        message=body.message,
        is_public=body.is_public,
        started_at=body.started_at or now,
        created_by_id=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(incident)
    await db.flush()

    note = IncidentNote(
        id=uuid4(),
        incident_id=incident.id,
        organization_id=org_id,
        note="Incident created.",
        status_change="investigating",
        created_by_id=user_id,
        created_at=now,
    )
    db.add(note)
    await db.commit()
    await db.refresh(incident)

    stmt = select(Incident).where(Incident.id == incident.id).options(selectinload(Incident.notes))
    incident = (await db.execute(stmt)).scalar_one()
    return _to_detail(incident)


# ---------------------------------------------------------------------------
# GET /admin/incidents/{incident_id}  — incident detail
# ---------------------------------------------------------------------------


@router.get("/admin/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: UUID,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> IncidentDetail:
    org_id = _org_id(principal)
    stmt = (
        select(Incident)
        .where(Incident.id == incident_id, Incident.organization_id == org_id)
        .options(selectinload(Incident.notes))
    )
    incident = (await db.execute(stmt)).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return _to_detail(incident)


# ---------------------------------------------------------------------------
# PATCH /admin/incidents/{incident_id}  — update incident
# ---------------------------------------------------------------------------


@router.patch("/admin/incidents/{incident_id}", response_model=IncidentDetail)
async def update_incident(
    incident_id: UUID,
    body: UpdateIncidentRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> IncidentDetail:
    org_id = _org_id(principal)
    user_id = _user_id(principal)

    stmt = (
        select(Incident)
        .where(Incident.id == incident_id, Incident.organization_id == org_id)
        .options(selectinload(Incident.notes))
    )
    incident = (await db.execute(stmt)).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    now = datetime.now(tz=UTC)
    old_status = incident.status
    status_changed = body.status is not None and body.status != old_status

    if body.title is not None:
        incident.title = body.title
    if body.status is not None:
        incident.status = body.status
    if body.severity is not None:
        incident.severity = body.severity
    if body.affected_services is not None:
        incident.affected_services = body.affected_services
    if body.message is not None:
        incident.message = body.message
    if body.is_public is not None:
        incident.is_public = body.is_public
    if body.resolved_at is not None:
        incident.resolved_at = body.resolved_at
    if body.status == "resolved" and incident.resolved_at is None:
        incident.resolved_at = now
    incident.updated_at = now

    if status_changed:
        note = IncidentNote(
            id=uuid4(),
            incident_id=incident.id,
            organization_id=org_id,
            note=f"Status changed from {old_status!r} to {body.status!r}.",
            status_change=body.status,
            created_by_id=user_id,
            created_at=now,
        )
        db.add(note)

    await db.commit()
    await db.refresh(incident)

    stmt = select(Incident).where(Incident.id == incident.id).options(selectinload(Incident.notes))
    incident = (await db.execute(stmt)).scalar_one()
    return _to_detail(incident)


# ---------------------------------------------------------------------------
# POST /admin/incidents/{incident_id}/notes  — add note
# ---------------------------------------------------------------------------


@router.post(
    "/admin/incidents/{incident_id}/notes",
    response_model=IncidentDetail,
    status_code=status.HTTP_201_CREATED,
)
async def add_incident_note(
    incident_id: UUID,
    body: AddIncidentNoteRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> IncidentDetail:
    org_id = _org_id(principal)
    user_id = _user_id(principal)

    stmt = (
        select(Incident)
        .where(Incident.id == incident_id, Incident.organization_id == org_id)
        .options(selectinload(Incident.notes))
    )
    incident = (await db.execute(stmt)).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    now = datetime.now(tz=UTC)
    note = IncidentNote(
        id=uuid4(),
        incident_id=incident.id,
        organization_id=org_id,
        note=body.note,
        status_change=body.status_change,
        created_by_id=user_id,
        created_at=now,
    )
    db.add(note)

    if body.status_change is not None and body.status_change != incident.status:
        if body.status_change == "resolved" and incident.resolved_at is None:
            incident.resolved_at = now
        incident.status = body.status_change
        incident.updated_at = now

    await db.commit()

    stmt = select(Incident).where(Incident.id == incident.id).options(selectinload(Incident.notes))
    incident = (await db.execute(stmt)).scalar_one()
    return _to_detail(incident)
