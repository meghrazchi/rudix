"""Admin endpoint for Enterprise Graph (Neo4j) health diagnostics (F279).

GET /admin/graph/health — returns enabled state, connection status, and safe
config metadata. Credentials and URIs with embedded auth are never returned.

Auth: owner/admin only.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.clients.neo4j_client import check_neo4j_health, get_driver
from app.core.config import settings
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/graph", tags=["admin-graph"])

GraphStatus = Literal["connected", "unavailable", "disabled"]


class GraphHealthResponse(BaseModel):
    enabled: bool
    status: GraphStatus
    database: str | None = None
    uri_configured: bool = False
    pool_size: int | None = None
    detail: str | None = None


@router.get("/health", response_model=GraphHealthResponse)
async def get_graph_health(
    _principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> GraphHealthResponse:
    """Return Neo4j Enterprise Graph health status.

    Never exposes credentials, passwords, or URI auth components.
    """
    if not settings.enterprise_graph_enabled:
        return GraphHealthResponse(enabled=False, status="disabled")

    driver_active = get_driver() is not None
    if not driver_active:
        return GraphHealthResponse(
            enabled=True,
            status="unavailable",
            uri_configured=bool(settings.neo4j_uri),
            database=settings.neo4j_database,
            pool_size=settings.neo4j_max_connection_pool_size,
            detail="neo4j_driver_not_initialized",
        )

    healthy = await check_neo4j_health()
    return GraphHealthResponse(
        enabled=True,
        status="connected" if healthy else "unavailable",
        uri_configured=bool(settings.neo4j_uri),
        database=settings.neo4j_database,
        pool_size=settings.neo4j_max_connection_pool_size,
        detail=None if healthy else "neo4j_query_failed",
    )
