"""Admin usage & adoption report endpoints (F353).

GET  /admin/usage-adoption/summary — top-level adoption metric counters
GET  /admin/usage-adoption/charts  — active-user trend, questions-per-user,
                                      feature usage, activation funnel,
                                      role adoption comparison, drop-off points
GET  /admin/usage-adoption/funnel  — activation funnel only
GET  /admin/usage-adoption/users   — filterable, paginated per-user table
GET  /admin/usage-adoption/export  — CSV export of the filtered user table
POST /admin/usage-adoption/users/{user_id}/onboarding-reminder — nudge email

"Invite user" reuses the existing team-invitation endpoints
(`team_invitations.py`); "view team usage" is just this page's own role
filter. Both are frontend-only affordances, not duplicated here.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.schemas.usage_adoption import (
    ActivationFunnelStepResponse,
    OnboardingReminderResponse,
    UsageAdoptionChartsResponse,
    UsageAdoptionSummaryResponse,
    UsageAdoptionUserListResponse,
)
from app.domains.admin.services.usage_adoption_service import (
    UsageAdoptionFilters,
    UsageAdoptionService,
)
from app.domains.email.services.email_service import EmailService
from app.models.enums import EmailEventType, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/usage-adoption", tags=["admin-usage-adoption"])
_service = UsageAdoptionService()
_email_service = EmailService()

_MAX_PAGE_SIZE = 200

_AdminRoles = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
]
_RateLimit = Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))]
_DB = Annotated[AsyncSession, Depends(get_db_session)]


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if not principal.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No active organization context"
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid organization context"
        ) from exc


def _build_filters(*, from_date, to_date, role: str | None) -> UsageAdoptionFilters:
    return UsageAdoptionFilters(from_date=from_date, to_date=to_date, role=role)


@router.get("/summary", response_model=UsageAdoptionSummaryResponse)
async def get_usage_adoption_summary(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    from_date: Annotated[str | None, Query(alias="from")] = None,
    to_date: Annotated[str | None, Query(alias="to")] = None,
    role: Annotated[str | None, Query()] = None,
) -> UsageAdoptionSummaryResponse:
    filters = _build_filters(
        from_date=_parse_date(from_date), to_date=_parse_date(to_date), role=role
    )
    return await _service.get_summary(
        db_session, organization_id=_org_id(principal), filters=filters
    )


@router.get("/charts", response_model=UsageAdoptionChartsResponse)
async def get_usage_adoption_charts(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    from_date: Annotated[str | None, Query(alias="from")] = None,
    to_date: Annotated[str | None, Query(alias="to")] = None,
    role: Annotated[str | None, Query()] = None,
) -> UsageAdoptionChartsResponse:
    filters = _build_filters(
        from_date=_parse_date(from_date), to_date=_parse_date(to_date), role=role
    )
    return await _service.get_charts(
        db_session, organization_id=_org_id(principal), filters=filters
    )


@router.get("/funnel", response_model=list[ActivationFunnelStepResponse])
async def get_usage_adoption_funnel(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    from_date: Annotated[str | None, Query(alias="from")] = None,
    to_date: Annotated[str | None, Query(alias="to")] = None,
    role: Annotated[str | None, Query()] = None,
) -> list[ActivationFunnelStepResponse]:
    filters = _build_filters(
        from_date=_parse_date(from_date), to_date=_parse_date(to_date), role=role
    )
    return await _service.get_activation_funnel(
        db_session, organization_id=_org_id(principal), filters=filters
    )


@router.get("/users", response_model=UsageAdoptionUserListResponse)
async def list_usage_adoption_users(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    from_date: Annotated[str | None, Query(alias="from")] = None,
    to_date: Annotated[str | None, Query(alias="to")] = None,
    role: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = 25,
) -> UsageAdoptionUserListResponse:
    filters = _build_filters(
        from_date=_parse_date(from_date), to_date=_parse_date(to_date), role=role
    )
    return await _service.list_users(
        db_session,
        organization_id=_org_id(principal),
        filters=filters,
        page=page,
        page_size=page_size,
    )


@router.get("/export")
async def export_usage_adoption(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    from_date: Annotated[str | None, Query(alias="from")] = None,
    to_date: Annotated[str | None, Query(alias="to")] = None,
    role: Annotated[str | None, Query()] = None,
) -> Response:
    filters = _build_filters(
        from_date=_parse_date(from_date), to_date=_parse_date(to_date), role=role
    )
    csv_content = await _service.build_export_csv(
        db_session, organization_id=_org_id(principal), filters=filters
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=usage-adoption.csv"},
    )


@router.post(
    "/users/{user_id}/onboarding-reminder",
    response_model=OnboardingReminderResponse,
)
async def send_onboarding_reminder(
    user_id: str,
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
) -> OnboardingReminderResponse:
    org_id = _org_id(principal)
    try:
        target_id = UUID(user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid user_id format"
        ) from exc

    member_stmt = (
        select(User, OrganizationMember)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == org_id, User.id == target_id)
    )
    row = (await db_session.execute(member_stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target_user, _member = row

    org = await db_session.get(Organization, org_id)
    org_name = org.name if org else ""

    sent = await _email_service.send_email(
        db_session,
        organization_id=org_id,
        user_id=target_user.id,
        recipient_email=target_user.email,
        event_type=EmailEventType.onboarding_reminder,
        template_name="onboarding_reminder.html",
        template_context={
            "recipient_name": target_user.display_name,
            "org_name": org_name,
        },
        subject=f"Finish setting up {org_name or 'Rudix'}",
    )
    await db_session.commit()
    return OnboardingReminderResponse(sent=sent)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dates must be in YYYY-MM-DD format",
        ) from exc
