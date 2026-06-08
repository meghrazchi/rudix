"""Settings - Billing endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.billing.schemas import (
    BillingContact,
    BillingContactUpdateRequest,
    BillingDateRange,
    BillingPlanInfo,
    BillingPortalSession,
    BillingQuota,
    BillingUsageSummary,
    Invoice,
)
from app.domains.billing.services import BillingService

router = APIRouter(prefix="/billing", tags=["billing"])

_service = BillingService()
_BILLING_VIEW = "billing:view"
_BILLING_MANAGE = "billing:manage"


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise ValueError("organization context required")
    return UUID(principal.organization_id)


@router.get("/plan", response_model=BillingPlanInfo)
async def get_billing_plan(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_BILLING_VIEW))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BillingPlanInfo:
    return await _service.get_plan_info(db_session, organization_id=_org_id(principal))


@router.get("/usage", response_model=BillingUsageSummary)
async def get_billing_usage(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_BILLING_VIEW))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    range_name: Annotated[BillingDateRange, Query(alias="range")] = BillingDateRange.thirty_days,
) -> BillingUsageSummary:
    return await _service.get_usage_summary(
        db_session,
        organization_id=_org_id(principal),
        range_name=range_name,
    )


@router.get("/quotas", response_model=list[BillingQuota])
async def get_billing_quotas(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_BILLING_VIEW))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[BillingQuota]:
    return await _service.get_quotas(db_session, organization_id=_org_id(principal))


@router.get("/invoices", response_model=list[Invoice])
async def get_invoices(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_BILLING_VIEW))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[Invoice]:
    return await _service.get_invoices(db_session, organization_id=_org_id(principal))


@router.get("/contact", response_model=BillingContact)
async def get_billing_contact(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_BILLING_VIEW))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BillingContact:
    return await _service.get_billing_contact(db_session, organization_id=_org_id(principal))


@router.patch("/contact", response_model=BillingContact)
async def update_billing_contact(
    payload: BillingContactUpdateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_BILLING_MANAGE))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BillingContact:
    return await _service.update_billing_contact(
        db_session,
        organization_id=_org_id(principal),
        payload=payload,
    )


@router.post("/portal-session", response_model=BillingPortalSession, status_code=status.HTTP_200_OK)
async def create_billing_portal_session(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_permission(_BILLING_MANAGE))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BillingPortalSession:
    return await _service.create_portal_session(
        db_session,
        organization_id=_org_id(principal),
    )
