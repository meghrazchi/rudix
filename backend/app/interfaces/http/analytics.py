from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.analytics.schemas.analytics import (
    AnalyticsEventIngestRequest,
    AnalyticsEventIngestResponse,
    AnalyticsSummaryResponse,
)
from app.domains.analytics.services.analytics_service import AnalyticsService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/analytics", tags=["analytics"])
analytics_service = AnalyticsService()


def _organization_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal organization context is invalid",
        ) from exc


@router.post("/events", response_model=AnalyticsEventIngestResponse)
async def ingest_event(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
                OrganizationRole.reviewer.value,
                OrganizationRole.developer.value,
                OrganizationRole.security_admin.value,
                OrganizationRole.billing_admin.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    body: AnalyticsEventIngestRequest,
) -> AnalyticsEventIngestResponse:
    organization_id = _organization_id_from_principal(principal)
    accepted, deduped = await analytics_service.record_event(
        db_session,
        organization_id=organization_id,
        user_id=UUID(principal.user_id),
        request=body,
    )
    await db_session.commit()
    return AnalyticsEventIngestResponse(
        accepted=accepted,
        deduped=deduped,
        enabled=accepted,
        event_name=body.event_name,
        schema_version=body.schema_version,
    )


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_admin_analytics_summary(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> AnalyticsSummaryResponse:
    organization_id = _organization_id_from_principal(principal)
    return await analytics_service.build_summary(
        db_session,
        organization_id=organization_id,
        from_date=from_date,
        to_date=to_date,
    )
