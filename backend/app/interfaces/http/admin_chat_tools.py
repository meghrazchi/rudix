"""Admin endpoint for chat tool availability (F342).

GET /admin/chat-tools/availability — returns per-tool availability for the
organisation, combining feature flag state and org-level policy overrides.
Admins can use PUT /admin/agent-policy/tools/{name} to disable specific tools.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.agents.repositories.agent_policy import AgentToolPolicyRepository
from app.domains.chat.services.tool_orchestrator import CHAT_TOOL_CAPABILITIES
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin", tags=["admin"])

_tool_policy_repo = AgentToolPolicyRepository()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ChatToolAvailabilityEntry(BaseModel):
    name: str
    purpose: str
    required_permission: str
    allowed_resource_types: list[str]
    approval_required: bool
    feature_flag: str | None
    required_roles: list[str]
    feature_available: bool
    org_policy_enabled: bool
    available: bool


class ChatToolsAvailabilityResponse(BaseModel):
    organization_id: str
    feature_enabled: bool
    tools: list[ChatToolAvailabilityEntry]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/chat-tools/availability", response_model=ChatToolsAvailabilityResponse)
async def get_chat_tools_availability(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatToolsAvailabilityResponse:
    """Return per-tool availability combining feature flags and org policy overrides."""
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        organization_id = UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc

    overrides = await _tool_policy_repo.list_by_organization(
        db_session, organization_id=organization_id
    )
    disabled_by_policy: set[str] = {o.tool_name for o in overrides if not o.enabled}

    feature_availability: dict[str, bool] = {
        "feature_enable_connectors": settings.feature_enable_connectors,
        "feature_enable_graph_rag": settings.feature_enable_graph_rag,
    }

    tools: list[ChatToolAvailabilityEntry] = []
    for cap in CHAT_TOOL_CAPABILITIES:
        feature_available = cap.feature_flag is None or feature_availability.get(
            cap.feature_flag, False
        )
        org_policy_enabled = cap.name not in disabled_by_policy
        tools.append(
            ChatToolAvailabilityEntry(
                name=cap.name,
                purpose=cap.purpose,
                required_permission=cap.required_permission,
                allowed_resource_types=list(cap.allowed_resource_types),
                approval_required=cap.approval_required,
                feature_flag=cap.feature_flag,
                required_roles=sorted(cap.required_roles),
                feature_available=feature_available,
                org_policy_enabled=org_policy_enabled,
                available=feature_available and org_policy_enabled,
            )
        )

    return ChatToolsAvailabilityResponse(
        organization_id=principal.organization_id,
        feature_enabled=settings.feature_enable_chat_tool_orchestration,
        tools=tools,
    )
