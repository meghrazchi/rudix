"""Admin endpoints for Enterprise Graph schema migrations (F280).

POST /admin/graph/migrate
    Apply pending graph migrations. Safe to call repeatedly (idempotent).

GET /admin/graph/migrations
    Return the list of __GraphMigration records currently stored in Neo4j.

Auth: owner/admin only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.graph.migration_runner import MigrationResult, get_migration_status, run_graph_migrations
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/graph", tags=["admin-graph"])


class MigrateResponse(BaseModel):
    success: bool
    applied: list[str]
    already_applied: list[str]
    failed: str | None = None


class MigrationRecord(BaseModel):
    version: str
    description: str
    applied_at: str


class MigrationsListResponse(BaseModel):
    enabled: bool
    migrations: list[MigrationRecord]


@router.post("/migrate", response_model=MigrateResponse, status_code=status.HTTP_200_OK)
async def trigger_graph_migrations(
    _principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> MigrateResponse:
    """Apply all pending graph schema migrations idempotently.

    Safe to call multiple times: already-applied migrations are skipped.
    Returns 503 if Enterprise Graph is enabled but the driver is unavailable.
    """
    if not settings.enterprise_graph_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="enterprise_graph_disabled",
        )

    result: MigrationResult = await run_graph_migrations()

    if result.failed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=result.failed,
        )

    return MigrateResponse(
        success=result.success,
        applied=result.applied,
        already_applied=result.already_applied,
        failed=result.failed,
    )


@router.get("/migrations", response_model=MigrationsListResponse)
async def list_graph_migrations(
    _principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> MigrationsListResponse:
    """Return the list of applied graph migrations from __GraphMigration nodes."""
    records = await get_migration_status()
    return MigrationsListResponse(
        enabled=settings.enterprise_graph_enabled,
        migrations=[MigrationRecord(**r) for r in records],
    )
