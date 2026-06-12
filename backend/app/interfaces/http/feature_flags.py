from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.schemas.feature_flags import PublicFeatureFlagsResponse
from app.domains.admin.services.feature_flag_service import FeatureFlagService
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])
_feature_flag_service = FeatureFlagService()


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
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


@router.get("", response_model=PublicFeatureFlagsResponse)
async def get_public_feature_flags(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.user))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PublicFeatureFlagsResponse:
    organization_id = _org_id(principal)
    return await _feature_flag_service.get_public_flags(
        db_session, organization_id=organization_id
    )
