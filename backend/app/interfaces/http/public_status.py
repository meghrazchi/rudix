from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db_session
from app.domains.admin.schemas.public_status import (
    PublicComponentState,
    PublicStatusComponent,
    PublicStatusIncident,
    PublicStatusSnapshot,
)
from app.models.incident import Incident
from app.models.organization import Organization

router = APIRouter(tags=["public-status"])

_ACTIVE_STATUSES: Final[frozenset[str]] = frozenset({"investigating", "identified", "monitoring"})
_HISTORY_LOOKBACK_DAYS: Final[int] = 30
_STATUS_COPY: Final[dict[PublicComponentState, tuple[str, str]]] = {
    "operational": ("All systems operational", "Rudix services are operating normally."),
    "degraded": (
        "Partial service degradation",
        "Some public services are slower or partially impaired.",
    ),
    "outage": (
        "Service interruption detected",
        "At least one public service is currently experiencing an outage.",
    ),
    "maintenance": (
        "Scheduled maintenance in progress",
        "One or more public services are undergoing planned or in-progress maintenance.",
    ),
    "unknown": (
        "Status information unavailable",
        "We could not determine the latest public service snapshot.",
    ),
}
_UPTIME_NOTICE = (
    "Status updates are published for transparency and do not imply an SLA unless one "
    "is explicitly contracted."
)
_PUBLIC_COMPONENTS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    ("web_app", "Web app", ("web", "frontend", "portal", "ui", "site")),
    ("api", "API", ("api", "backend", "service", "gateway")),
    (
        "documents",
        "Document processing",
        ("document", "upload", "ingest", "index", "extract"),
    ),
    (
        "answering",
        "Retrieval and chat",
        ("chat", "retrieval", "search", "answer", "citation"),
    ),
    (
        "integrations",
        "Integrations",
        ("connector", "sync", "slack", "teams", "drive", "confluence"),
    ),
)


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_maintenance_incident(incident: Incident) -> bool:
    haystacks = [
        _normalize_text(incident.title),
        _normalize_text(incident.message),
        *[_normalize_text(service) for service in incident.affected_services or []],
    ]
    return any("maintenance" in value for value in haystacks)


def _incident_matches_component(incident: Incident, keywords: tuple[str, ...]) -> bool:
    haystacks = [
        _normalize_text(incident.title),
        _normalize_text(incident.message),
        *[_normalize_text(service) for service in incident.affected_services or []],
    ]
    return any(keyword in haystack for keyword in keywords for haystack in haystacks)


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 99)


def _state_copy(state: PublicComponentState) -> tuple[str, str]:
    return _STATUS_COPY[state]


def _incident_kind(incident: Incident) -> Literal["incident", "maintenance"]:
    return "maintenance" if _is_maintenance_incident(incident) else "incident"


def _incident_summary(incident: Incident) -> PublicStatusIncident:
    return PublicStatusIncident(
        title=incident.title,
        status=incident.status,
        severity=incident.severity,
        kind=_incident_kind(incident),
        affected_services=list(incident.affected_services or []),
        message=incident.message,
        started_at=incident.started_at,
        resolved_at=incident.resolved_at,
    )


async def _resolve_public_organization_id(db_session: AsyncSession) -> UUID | None:
    slug = (settings.public_status_organization_slug or "").strip()
    if not slug:
        return None

    result = await db_session.execute(select(Organization.id).where(Organization.slug == slug))
    organization_id = result.scalar_one_or_none()
    return organization_id


def _component_state(
    *,
    incidents: list[Incident],
    current_maintenance_active: bool,
    keywords: tuple[str, ...],
) -> PublicComponentState:
    matching = [
        incident for incident in incidents if _incident_matches_component(incident, keywords)
    ]
    if current_maintenance_active and any(
        not incident.affected_services or _incident_matches_component(incident, keywords)
        for incident in incidents
        if _is_maintenance_incident(incident)
    ):
        return "maintenance"
    if not matching:
        return "operational"

    highest = min(matching, key=lambda incident: _severity_rank(incident.severity))
    if highest.severity in {"critical", "high"}:
        return "outage"
    if highest.severity in {"medium", "low"}:
        return "degraded"
    return "unknown"


def _component_updated_at(
    incidents: list[Incident], *, keywords: tuple[str, ...]
) -> datetime | None:
    timestamps = [
        _as_utc_datetime(incident.updated_at)
        for incident in incidents
        if _incident_matches_component(incident, keywords)
    ]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    if not timestamps:
        return None
    return max(timestamps)


def _build_components(
    incidents: list[Incident],
    *,
    current_maintenance_active: bool,
) -> list[PublicStatusComponent]:
    components: list[PublicStatusComponent] = []
    for key, label, keywords in _PUBLIC_COMPONENTS:
        state = _component_state(
            incidents=incidents,
            current_maintenance_active=current_maintenance_active,
            keywords=keywords,
        )
        summary = _state_copy(state)[1]
        affected_services = sorted(
            {
                service
                for incident in incidents
                for service in (incident.affected_services or [])
                if _incident_matches_component(incident, keywords)
            }
        )
        components.append(
            PublicStatusComponent(
                key=key,
                label=label,
                status=state,
                summary=summary,
                affected_services=affected_services,
                updated_at=_component_updated_at(incidents, keywords=keywords),
            )
        )
    return components


def _overall_state(components: list[PublicStatusComponent]) -> PublicComponentState:
    statuses = {component.status for component in components}
    if "maintenance" in statuses:
        return "maintenance"
    if "outage" in statuses:
        return "outage"
    if "degraded" in statuses:
        return "degraded"
    if statuses == {"operational"}:
        return "operational"
    if not statuses:
        return "unknown"
    return "unknown"


@router.get("/status", response_model=PublicStatusSnapshot)
async def get_public_status(
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PublicStatusSnapshot:
    now = datetime.now(tz=UTC)
    organization_id = await _resolve_public_organization_id(db_session)
    if organization_id is None:
        components = _build_components([], current_maintenance_active=False)
        headline, summary = _state_copy("operational")
        return PublicStatusSnapshot(
            generated_at=now,
            overall_status="operational",
            headline=headline,
            summary=summary,
            components=components,
            current_incidents=[],
            scheduled_maintenance=[],
            recent_history=[],
            uptime_notice=_UPTIME_NOTICE,
        )

    active_stmt = (
        select(Incident)
        .where(
            Incident.organization_id == organization_id,
            Incident.is_public.is_(True),
            Incident.status.in_(list(_ACTIVE_STATUSES)),
        )
        .order_by(Incident.started_at.desc())
    )
    active_incidents = list((await db_session.execute(active_stmt)).scalars().all())

    history_cutoff = now - timedelta(days=_HISTORY_LOOKBACK_DAYS)
    history_stmt = (
        select(Incident)
        .where(
            Incident.organization_id == organization_id,
            Incident.is_public.is_(True),
            Incident.status == "resolved",
            Incident.resolved_at >= history_cutoff,
        )
        .order_by(Incident.resolved_at.desc(), Incident.started_at.desc())
    )
    recent_history = list((await db_session.execute(history_stmt)).scalars().all())

    maintenance_incidents = [
        incident for incident in active_incidents if _is_maintenance_incident(incident)
    ]
    current_maintenance = [
        incident
        for incident in maintenance_incidents
        if (_as_utc_datetime(incident.started_at) or now) <= now and incident.status != "identified"
    ]
    scheduled_maintenance = sorted(
        maintenance_incidents,
        key=lambda incident: incident.started_at,
        reverse=True,
    )
    current_incidents = [
        incident
        for incident in active_incidents
        if not _is_maintenance_incident(incident)
        and (_as_utc_datetime(incident.started_at) or now) <= now
    ]

    components = _build_components(
        current_incidents + current_maintenance,
        current_maintenance_active=bool(current_maintenance),
    )
    overall_state = _overall_state(components)
    headline, summary = _state_copy(overall_state)

    return PublicStatusSnapshot(
        generated_at=now,
        overall_status=overall_state,
        headline=headline,
        summary=summary,
        components=components,
        current_incidents=[_incident_summary(incident) for incident in current_incidents],
        scheduled_maintenance=[_incident_summary(incident) for incident in scheduled_maintenance],
        recent_history=[_incident_summary(incident) for incident in recent_history[:10]],
        uptime_notice=_UPTIME_NOTICE,
    )
