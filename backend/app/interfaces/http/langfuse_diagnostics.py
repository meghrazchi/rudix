"""Admin endpoint for Langfuse observability diagnostics (F271).

GET /admin/langfuse/status — returns enabled, key, reachability, and client
state without exposing any secrets.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.langfuse_tracer import check_langfuse_health
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/langfuse", tags=["admin-langfuse"])


@router.get("/status")
async def get_langfuse_status(
    _principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> dict[str, object]:
    """Return Langfuse integration status safe for admin display.

    Never exposes keys, base URL credentials, or trace content.
    """
    return await check_langfuse_health()
