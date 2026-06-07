from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.connectors.schemas.observability import ConnectorPlatformHealthResponse
from app.domains.connectors.services.platform_observability import (
    ConnectorPlatformObservabilityService,
)
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/connectors", tags=["connector-platform"])

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


def _service() -> ConnectorPlatformObservabilityService:
    return ConnectorPlatformObservabilityService()


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


@router.get("/health", response_model=ConnectorPlatformHealthResponse)
async def get_connector_platform_health(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> ConnectorPlatformHealthResponse:
    try:
        snapshot = await _service().build_health_snapshot(
            db_session,
            organization_id=_org_id(principal),
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    payload = asdict(snapshot)
    payload["organization_id"] = str(payload["organization_id"])
    return ConnectorPlatformHealthResponse.model_validate(payload)
