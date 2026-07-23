from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.reports.schemas.reports import (
    AnswerQualityDetailResponse,
    AnswerQualityReportResponse,
    ReportCategory,
    ReportEventAccepted,
    ReportEventCreate,
    ReportResponse,
    ReportSort,
    SortDirection,
)
from app.domains.reports.services.answer_quality_service import AnswerQualityService
from app.domains.reports.services.report_service import ReportService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/reports", tags=["reports"])
service = ReportService()
answer_quality_service = AnswerQualityService()
ReportPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
]
AnswerQualityPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(
        require_roles(
            OrganizationRole.owner.value,
            OrganizationRole.admin.value,
            OrganizationRole.reviewer.value,
        )
    ),
]


def _ids(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    try:
        if principal.organization_id is None:
            raise ValueError
        return UUID(principal.organization_id), UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid organization context"
        ) from exc


@router.post("/events", response_model=ReportEventAccepted, status_code=status.HTTP_201_CREATED)
async def create_report_event(
    principal: ReportPrincipal,
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    body: ReportEventCreate,
) -> ReportEventAccepted:
    organization_id, user_id = _ids(principal)
    result = await service.record_event(
        session, organization_id=organization_id, user_id=user_id, event=body
    )
    await session.commit()
    return result


@router.get("", response_model=ReportResponse)
async def get_report(
    principal: ReportPrincipal,
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
    category: ReportCategory | None = None,
    workspace_id: UUID | None = None,
    collection_id: UUID | None = None,
    connector_id: UUID | None = None,
    user_id: UUID | None = None,
    team_id: UUID | None = None,
    source_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: ReportSort = "occurred_at",
    direction: SortDirection = "desc",
) -> ReportResponse:
    organization_id, _user_id = _ids(principal)
    resolved_to = to_at or datetime.now(tz=UTC)
    resolved_from = from_at or resolved_to - timedelta(days=29)
    if resolved_from.tzinfo is None or resolved_to.tzinfo is None:
        raise HTTPException(status_code=422, detail="Report timestamps must include a timezone")
    if resolved_from > resolved_to:
        raise HTTPException(status_code=422, detail="from must be before or equal to to")
    if resolved_to - resolved_from > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Report date range cannot exceed 366 days")
    return await service.build_report(
        session,
        organization_id=organization_id,
        from_at=resolved_from,
        to_at=resolved_to,
        category=category,
        workspace_id=workspace_id,
        collection_id=collection_id,
        connector_id=connector_id,
        user_id=user_id,
        team_id=team_id,
        source_id=source_id,
        page=page,
        page_size=page_size,
        sort=sort,
        direction=direction,
    )


@router.get("/answer-quality", response_model=AnswerQualityReportResponse)
async def get_answer_quality_report(
    principal: AnswerQualityPrincipal,
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
    collection_id: UUID | None = None,
    source_id: UUID | None = None,
    user_id: UUID | None = None,
    warning: str | None = Query(default=None, max_length=64),
    confidence: str | None = Query(
        default=None, pattern="^(all|high|medium|low|warning|not_found)$"
    ),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 25,
    sort: str = Query(default="created_at", pattern="^(created_at|confidence|citation_support)$"),
    direction: SortDirection = "desc",
) -> AnswerQualityReportResponse:
    organization_id, viewer_user_id = _ids(principal)
    resolved_to = to_at or datetime.now(tz=UTC)
    resolved_from = from_at or resolved_to - timedelta(days=29)
    if resolved_from.tzinfo is None or resolved_to.tzinfo is None:
        raise HTTPException(status_code=422, detail="Report timestamps must include a timezone")
    if resolved_from > resolved_to:
        raise HTTPException(status_code=422, detail="from must be before or equal to to")
    if resolved_to - resolved_from > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Report date range cannot exceed 366 days")
    return await answer_quality_service.build_report(
        session,
        organization_id=organization_id,
        viewer_user_id=viewer_user_id,
        viewer_roles=principal.roles,
        from_at=resolved_from,
        to_at=resolved_to,
        collection_id=collection_id,
        source_id=source_id,
        user_id=user_id,
        warning=warning,
        confidence_level=confidence,
        page=page,
        page_size=page_size,
        sort=sort,
        direction=direction,
    )


@router.get("/answer-quality/{message_id}", response_model=AnswerQualityDetailResponse)
async def get_answer_quality_detail(
    message_id: UUID,
    principal: AnswerQualityPrincipal,
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnswerQualityDetailResponse:
    organization_id, viewer_user_id = _ids(principal)
    detail = await answer_quality_service.get_detail(
        session,
        organization_id=organization_id,
        viewer_user_id=viewer_user_id,
        viewer_roles=principal.roles,
        message_id=message_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Answer not found or inaccessible")
    return detail
