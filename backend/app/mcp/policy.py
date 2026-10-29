from __future__ import annotations

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.agents.schemas import ToolSpec
from app.models.mcp_policy import OrgMCPPolicy


def derive_mcp_capabilities(
    principal: AuthenticatedPrincipal,
    *,
    org_policy: OrgMCPPolicy | None = None,
) -> set[str]:
    role_capabilities = {
        "owner": (
            org_policy.capabilities_owner
            if org_policy is not None and org_policy.capabilities_owner is not None
            else settings.mcp_capabilities_owner
        ),
        "admin": (
            org_policy.capabilities_admin
            if org_policy is not None and org_policy.capabilities_admin is not None
            else settings.mcp_capabilities_admin
        ),
        "member": (
            org_policy.capabilities_member
            if org_policy is not None and org_policy.capabilities_member is not None
            else settings.mcp_capabilities_member
        ),
        "viewer": (
            org_policy.capabilities_viewer
            if org_policy is not None and org_policy.capabilities_viewer is not None
            else settings.mcp_capabilities_viewer
        ),
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
    org_policy: OrgMCPPolicy | None = None,
) -> None:
    capabilities = derive_mcp_capabilities(principal, org_policy=org_policy)
    required_capability = tool_spec.capability.strip().lower()
    if required_capability not in capabilities:
        raise AuthorizationError("Principal capability is not authorized for this MCP tool")
