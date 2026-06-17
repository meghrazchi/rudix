from __future__ import annotations

from app.models.mcp_policy import OrgMCPPolicy

_REDACTED_PLACEHOLDER = "[content redacted by MCP trust policy]"
_TRUNCATION_SUFFIX = "… [truncated by MCP trust policy]"


class AllowlistDenied(Exception):
    """Raised when an MCP operation is blocked by an org allowlist."""

    def __init__(self, resource_type: str, name: str) -> None:
        self.resource_type = resource_type
        self.name = name
        super().__init__(f"{resource_type} not in allowlist: {name!r}")


class PayloadTooLarge(Exception):
    """Raised when an MCP request or response exceeds the configured byte limit."""

    def __init__(self, direction: str, size: int, limit: int) -> None:
        self.direction = direction
        self.size = size
        self.limit = limit
        super().__init__(f"{direction} payload {size} bytes exceeds limit {limit}")


class MCPTrustService:
    """Enforces trust controls defined in OrgMCPPolicy for MCP operations.

    All check_* methods raise the appropriate exception when a constraint is
    violated.  Callers in the MCP server layer should catch and convert these
    to the appropriate MCP error response.
    """

    def check_tool_allowed(self, policy: OrgMCPPolicy, tool_name: str) -> None:
        """Raise AllowlistDenied if tool_name is not in the allowed_tools list.

        A null allowed_tools means no restriction — all tools are permitted.
        """
        allowed = policy.allowed_tools
        if allowed is None:
            return
        if tool_name not in allowed:
            raise AllowlistDenied("tool", tool_name)

    def check_resource_allowed(self, policy: OrgMCPPolicy, resource_uri: str) -> None:
        """Raise AllowlistDenied if resource_uri is not covered by allowed_resources.

        Patterns ending with '*' match any URI that starts with the prefix.
        Exact-match patterns are also supported.
        """
        allowed = policy.allowed_resources
        if allowed is None:
            return
        for pattern in allowed:
            if pattern.endswith("*"):
                if resource_uri.startswith(pattern[:-1]):
                    return
            elif resource_uri == pattern:
                return
        raise AllowlistDenied("resource", resource_uri)

    def check_prompt_allowed(self, policy: OrgMCPPolicy, prompt_name: str) -> None:
        """Raise AllowlistDenied if prompt_name is not in allowed_prompts."""
        allowed = policy.allowed_prompts
        if allowed is None:
            return
        if prompt_name not in allowed:
            raise AllowlistDenied("prompt", prompt_name)

    def check_collection_allowed(self, policy: OrgMCPPolicy, collection_id: str) -> None:
        """Raise AllowlistDenied if collection_id is not in allowed_collections."""
        allowed = policy.allowed_collections
        if allowed is None:
            return
        if collection_id not in allowed:
            raise AllowlistDenied("collection", collection_id)

    def check_role_allowed(self, policy: OrgMCPPolicy, role: str) -> None:
        """Raise AllowlistDenied if role is not in allowed_roles.

        A null allowed_roles means all org roles may use MCP.
        """
        allowed_roles = policy.allowed_roles
        if allowed_roles is None:
            return
        if role not in allowed_roles:
            raise AllowlistDenied("role", role)

    def redact_chunk_text(self, policy: OrgMCPPolicy, text: str) -> str:
        """Return document text processed through the redaction/truncation policy.

        When redact_document_text=True (default) and max_chunk_chars is set,
        text is truncated at that limit.  When redact_document_text=True and
        no char limit is configured, the full text is replaced with a placeholder
        to prevent raw document leakage.

        When redact_document_text=False, raw text is allowed and only the
        char limit applies (if configured).
        """
        if policy.redact_document_text:
            if policy.max_chunk_chars is not None:
                if len(text) > policy.max_chunk_chars:
                    return text[: policy.max_chunk_chars] + _TRUNCATION_SUFFIX
                return text
            return _REDACTED_PLACEHOLDER

        if policy.max_chunk_chars is not None and len(text) > policy.max_chunk_chars:
            return text[: policy.max_chunk_chars] + _TRUNCATION_SUFFIX
        return text

    def enforce_request_size(self, policy: OrgMCPPolicy, body_bytes: int) -> None:
        """Raise PayloadTooLarge if body_bytes exceeds max_request_bytes."""
        limit = policy.max_request_bytes
        if limit is not None and body_bytes > limit:
            raise PayloadTooLarge("request", body_bytes, limit)

    def enforce_response_size(self, policy: OrgMCPPolicy, body_bytes: int) -> None:
        """Raise PayloadTooLarge if body_bytes exceeds max_response_bytes."""
        limit = policy.max_response_bytes
        if limit is not None and body_bytes > limit:
            raise PayloadTooLarge("response", body_bytes, limit)
