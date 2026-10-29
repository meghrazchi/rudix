from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.domains.mcp.repository import MCPPolicyRepository
from app.domains.mcp.trust_service import (
    AllowlistDenied,
    MCPTrustService,
    PayloadTooLarge,
)
from app.models.mcp_policy import OrgMCPPolicy

__all__ = [
    "PayloadTooLarge",
    "apply_org_mcp_output_policy",
    "enforce_org_mcp_prompt_policy",
    "enforce_org_mcp_resource_policy",
    "enforce_org_mcp_tool_policy",
    "load_org_mcp_policy",
]

_logger = get_logger("mcp.trust_guard")
_policy_repo = MCPPolicyRepository()
_trust_service = MCPTrustService()


async def load_org_mcp_policy(organization_id: str | None) -> OrgMCPPolicy | None:
    """Load the persisted OrgMCPPolicy for *organization_id*, or None if unconfigured."""
    if not organization_id:
        return None
    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        return None

    try:
        async with SessionLocal() as session:
            return await _policy_repo.get(session, organization_id=org_uuid)
    except Exception as exc:
        _logger.debug(
            "mcp.trust_guard.policy_lookup_skipped",
            organization_id=organization_id,
            error=exc.__class__.__name__,
        )
        return None


def _ensure_org_policy_enabled_and_role_allowed(
    policy: OrgMCPPolicy,
    principal: AuthenticatedPrincipal,
) -> None:
    if not policy.enabled:
        raise AuthorizationError("MCP is disabled by organization policy.")

    if policy.allowed_roles is not None:
        normalized_roles = [role.strip().lower() for role in principal.roles if role.strip()]
        if not normalized_roles:
            raise AuthorizationError("Principal role is not allowed by organization MCP policy.")
        for role in normalized_roles:
            try:
                _trust_service.check_role_allowed(policy, role)
                return
            except AllowlistDenied:
                continue
        raise AuthorizationError("Principal role is not allowed by organization MCP policy.")


def enforce_org_mcp_tool_policy(
    *,
    policy: OrgMCPPolicy | None,
    principal: AuthenticatedPrincipal,
    tool_name: str,
    internal_tool_name: str,
    arguments: dict[str, Any] | None,
) -> None:
    """Enforce OrgMCPPolicy enabled, role, tool allowlist, and request size controls."""
    if policy is None:
        return

    _ensure_org_policy_enabled_and_role_allowed(policy, principal)

    if policy.allowed_tools is not None:
        try:
            _trust_service.check_tool_allowed(policy, tool_name)
        except AllowlistDenied as exc:
            try:
                _trust_service.check_tool_allowed(policy, internal_tool_name)
            except AllowlistDenied:
                raise AuthorizationError("Tool is not allowed by organization MCP policy.") from exc

    encoded_args = json.dumps(arguments or {}, default=str).encode("utf-8")
    _trust_service.enforce_request_size(policy, len(encoded_args))


def enforce_org_mcp_resource_policy(
    *,
    policy: OrgMCPPolicy | None,
    principal: AuthenticatedPrincipal,
    resource: str,
) -> None:
    """Enforce OrgMCPPolicy enabled, role, and resource allowlist controls."""
    if policy is None:
        return

    _ensure_org_policy_enabled_and_role_allowed(policy, principal)

    if policy.allowed_resources is not None:
        candidates = (resource, f"rudix://{resource}", f"rag://{resource}")
        allowed = False
        for candidate in candidates:
            try:
                _trust_service.check_resource_allowed(policy, candidate)
                allowed = True
                break
            except AllowlistDenied:
                continue
        if not allowed:
            raise AuthorizationError("Resource is not allowed by organization MCP policy.")


def enforce_org_mcp_prompt_policy(
    *,
    policy: OrgMCPPolicy | None,
    principal: AuthenticatedPrincipal,
    prompt_name: str,
) -> None:
    """Enforce OrgMCPPolicy enabled, role, and prompt allowlist controls."""
    if policy is None:
        return

    _ensure_org_policy_enabled_and_role_allowed(policy, principal)

    try:
        _trust_service.check_prompt_allowed(policy, prompt_name)
    except AllowlistDenied as exc:
        raise AuthorizationError("Prompt is not allowed by organization MCP policy.") from exc


def apply_org_mcp_output_policy(
    *,
    policy: OrgMCPPolicy | None,
    output: dict[str, Any],
) -> dict[str, Any]:
    """Apply OrgMCPPolicy chunk text redaction/truncation and response byte limits."""
    if policy is None:
        return output

    redacted = dict(output)
    items = redacted.get("items")
    if isinstance(items, list):
        new_items: list[Any] = []
        for item in items:
            if isinstance(item, dict):
                updated_item = dict(item)
                for field_name in ("preview", "text", "content", "snippet"):
                    val = updated_item.get(field_name)
                    if isinstance(val, str):
                        updated_item[field_name] = _trust_service.redact_chunk_text(policy, val)
                new_items.append(updated_item)
            else:
                new_items.append(item)
        redacted["items"] = new_items

    citations = redacted.get("citations")
    if isinstance(citations, list):
        new_citations: list[Any] = []
        for citation in citations:
            if isinstance(citation, dict):
                updated_citation = dict(citation)
                snippet = updated_citation.get("snippet")
                if isinstance(snippet, str):
                    updated_citation["snippet"] = _trust_service.redact_chunk_text(policy, snippet)
                new_citations.append(updated_citation)
            else:
                new_citations.append(citation)
        redacted["citations"] = new_citations

    encoded_output = json.dumps(redacted, default=str).encode("utf-8")
    _trust_service.enforce_response_size(policy, len(encoded_output))
    return redacted
