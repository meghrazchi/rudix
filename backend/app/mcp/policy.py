from __future__ import annotations

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.agents.schemas import ToolSpec


def derive_mcp_capabilities(principal: AuthenticatedPrincipal) -> set[str]:
    role_capabilities = {
        "owner": settings.mcp_capabilities_owner,
        "admin": settings.mcp_capabilities_admin,
        "member": settings.mcp_capabilities_member,
        "viewer": settings.mcp_capabilities_viewer,
    }
    capabilities: set[str] = set()
    for role in principal.roles:
        normalized_role = role.strip().lower()
        for capability in role_capabilities.get(normalized_role, []):
            capabilities.add(capability.strip().lower())
    return capabilities


def ensure_mcp_tool_capability(
    *,
    principal: AuthenticatedPrincipal,
    tool_spec: ToolSpec,
) -> None:
    capabilities = derive_mcp_capabilities(principal)
    required_capability = tool_spec.capability.strip().lower()
    if required_capability not in capabilities:
        raise AuthorizationError("Principal capability is not authorized for this MCP tool")
