"""Admin vector index status (R06-08).

GET /admin/vector-index/status — read-only: active embedding model, a building
generation, and the caller's organisation's reindex progress. Build, swap, and rollback
are operator commands (``scripts/vector_index.py``); there is no write endpoint.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.vector_index.schemas.vector_index import VectorIndexStatusResponse
from app.domains.vector_index.services.status_service import organization_status
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/vector-index", tags=["admin-vector-index"])

_AdminRoles = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
]
_RateLimit = Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))]
_DB = Annotated[AsyncSession, Depends(get_db_session)]


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(str(principal.organization_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid organization context"
        ) from exc


@router.get("/status", response_model=VectorIndexStatusResponse)
async def get_vector_index_status(
    principal: _AdminRoles, _: _RateLimit, db: _DB
) -> VectorIndexStatusResponse:
    return await organization_status(db, organization_id=_org_id(principal))
