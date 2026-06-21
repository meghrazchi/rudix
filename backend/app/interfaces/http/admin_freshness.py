"""Admin endpoints for org-level freshness threshold configuration (F311).

GET  /admin/settings/freshness-thresholds  → current policy (or defaults if no row)
PATCH /admin/settings/freshness-thresholds → upsert policy
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.models.enums import OrganizationRole
from app.models.org_freshness_policy import OrgFreshnessPolicy
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_DAYS_FIELD = Field(default=None, ge=1, le=3650)


class FreshnessThresholdsResponse(BaseModel):
    """Current org freshness policy thresholds (defaults shown when no row exists)."""

    organization_id: str
    warn_stale_after_days: int | None
    warn_unreviewed_after_days: int | None
    auto_exclude_deprecated: bool
    auto_exclude_expired: bool
    label: str | None
    updated_at: datetime | None


class PatchFreshnessThresholdsRequest(BaseModel):
    warn_stale_after_days: int | None = _DAYS_FIELD
    warn_unreviewed_after_days: int | None = _DAYS_FIELD
    auto_exclude_deprecated: bool | None = None
    auto_exclude_expired: bool | None = None
    label: str | None = Field(default=None, max_length=255)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _policy_to_response(
    policy: OrgFreshnessPolicy | None,
    organization_id: UUID,
) -> FreshnessThresholdsResponse:
    if policy is None:
        return FreshnessThresholdsResponse(
            organization_id=str(organization_id),
            warn_stale_after_days=None,
            warn_unreviewed_after_days=None,
            auto_exclude_deprecated=True,
            auto_exclude_expired=True,
            label=None,
            updated_at=None,
        )
    return FreshnessThresholdsResponse(
        organization_id=str(organization_id),
        warn_stale_after_days=policy.warn_stale_after_days,
        warn_unreviewed_after_days=policy.warn_unreviewed_after_days,
        auto_exclude_deprecated=policy.auto_exclude_deprecated,
        auto_exclude_expired=policy.auto_exclude_expired,
        label=policy.label,
        updated_at=policy.updated_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/settings/freshness-thresholds",
    response_model=FreshnessThresholdsResponse,
    summary="Get org freshness threshold policy",
    description=(
        "Returns the current org-level freshness warning thresholds. "
        "When no policy row exists the response shows the system defaults "
        "(warn_stale_after_days=null means use per-document stale_after_days or 90 days, "
        "auto_exclude_deprecated=true, auto_exclude_expired=true)."
    ),
)
async def get_freshness_thresholds(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FreshnessThresholdsResponse:
    organization_id = _org_id(principal)
    result = await db_session.execute(
        select(OrgFreshnessPolicy).where(
            OrgFreshnessPolicy.organization_id == organization_id
        )
    )
    policy = result.scalar_one_or_none()
    return _policy_to_response(policy, organization_id)


@router.patch(
    "/settings/freshness-thresholds",
    response_model=FreshnessThresholdsResponse,
    summary="Update org freshness threshold policy",
    description=(
        "Upserts the org-level freshness warning thresholds. "
        "Only fields included in the request body are changed. "
        "To clear a days threshold set its value to null."
    ),
)
async def patch_freshness_thresholds(
    payload: PatchFreshnessThresholdsRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FreshnessThresholdsResponse:
    organization_id = _org_id(principal)
    result = await db_session.execute(
        select(OrgFreshnessPolicy).where(
            OrgFreshnessPolicy.organization_id == organization_id
        )
    )
    policy = result.scalar_one_or_none()

    updates = payload.model_dump(exclude_unset=True)

    if policy is None:
        policy = OrgFreshnessPolicy(
            id=uuid4(),
            organization_id=organization_id,
            warn_stale_after_days=updates.get("warn_stale_after_days"),
            warn_unreviewed_after_days=updates.get("warn_unreviewed_after_days"),
            auto_exclude_deprecated=updates.get("auto_exclude_deprecated", True),
            auto_exclude_expired=updates.get("auto_exclude_expired", True),
            label=updates.get("label"),
        )
        db_session.add(policy)
    else:
        for field, value in updates.items():
            setattr(policy, field, value)
        policy.updated_at = datetime.now(tz=UTC)

    await db_session.commit()
    await db_session.refresh(policy)
    return _policy_to_response(policy, organization_id)
