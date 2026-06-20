from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.models.enums import OrganizationRole
from app.models.organization import Organization

router = APIRouter(prefix="/admin/onboarding", tags=["admin-onboarding"])


class OnboardingConfigResponse(BaseModel):
    sample_docs_enabled: bool
    reset_at: datetime | None


class PatchOnboardingConfigRequest(BaseModel):
    sample_docs_enabled: bool | None = None


@router.get("/config", response_model=OnboardingConfigResponse)
async def get_onboarding_config(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles([OrganizationRole.owner, OrganizationRole.admin]))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingConfigResponse:
    org = await _get_org(db, principal.organization_id)
    return OnboardingConfigResponse(
        sample_docs_enabled=org.sample_docs_enabled,
        reset_at=org.onboarding_reset_at,
    )


@router.patch("/config", response_model=OnboardingConfigResponse)
async def patch_onboarding_config(
    body: PatchOnboardingConfigRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles([OrganizationRole.owner, OrganizationRole.admin]))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingConfigResponse:
    org = await _get_org(db, principal.organization_id)
    if body.sample_docs_enabled is not None:
        org.sample_docs_enabled = body.sample_docs_enabled
    await db.commit()
    await db.refresh(org)
    return OnboardingConfigResponse(
        sample_docs_enabled=org.sample_docs_enabled,
        reset_at=org.onboarding_reset_at,
    )


@router.post("/reset", response_model=OnboardingConfigResponse)
async def reset_onboarding(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles([OrganizationRole.owner, OrganizationRole.admin]))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OnboardingConfigResponse:
    """Set reset_at to now so all org users re-show the onboarding checklist."""
    org = await _get_org(db, principal.organization_id)
    org.onboarding_reset_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(org)
    return OnboardingConfigResponse(
        sample_docs_enabled=org.sample_docs_enabled,
        reset_at=org.onboarding_reset_at,
    )


async def _get_org(db: AsyncSession, organization_id: UUID) -> Organization:
    result = await db.execute(select(Organization).where(Organization.id == organization_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org
