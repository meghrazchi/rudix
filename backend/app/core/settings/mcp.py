"""MCP server and external MCP connector settings."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)
from pydantic_settings import NoDecode

from app.core.settings.enums import (
    _ALLOWED_ORG_ROLES,
    _DEFAULT_MCP_ELEVATED_CAPABILITIES,
    _DEFAULT_MCP_VIEWER_CAPABILITIES,
    Environment,
    MCPExternalAuthType,
    MCPExternalServerSettings,
    MCPTransport,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class McpSettings(BaseModel):
    feature_enable_mcp: bool = False
    feature_enable_external_mcp_connectors: bool = False
    mcp_server_name: str = Field(default="Rudix MCP Server", min_length=3, max_length=120)
    mcp_transport: MCPTransport = MCPTransport.streamable_http
    mcp_http_host: str = Field(default="0.0.0.0", min_length=1, max_length=255)
    mcp_http_port: int = Field(default=8010, ge=1, le=65535)
    mcp_http_path: str = Field(default="/mcp", pattern=r"^/[a-zA-Z0-9/_-]*$")
    mcp_require_bearer_auth: bool = True
    mcp_dev_principal_user_id: str | None = Field(default=None, min_length=3, max_length=128)
    mcp_dev_principal_organization_id: str | None = Field(
        default=None, min_length=3, max_length=128
    )
    mcp_dev_principal_roles: Annotated[list[str], NoDecode] = Field(default_factory=list)
    mcp_capabilities_owner: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_MCP_ELEVATED_CAPABILITIES)
    )
    mcp_capabilities_admin: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_MCP_ELEVATED_CAPABILITIES)
    )
    mcp_capabilities_member: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_MCP_ELEVATED_CAPABILITIES)
    )
    mcp_capabilities_viewer: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_MCP_VIEWER_CAPABILITIES)
    )
    mcp_rate_limit_enabled: bool = True
    mcp_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    mcp_rate_limit_requests: int = Field(default=30, ge=1, le=10000)
    mcp_external_servers: Annotated[list[MCPExternalServerSettings], NoDecode] = Field(
        default_factory=list
    )

    @field_validator("mcp_dev_principal_roles", mode="before")
    @classmethod
    def validate_mcp_dev_principal_roles(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("mcp_dev_principal_roles must be a comma-separated string or list")

        normalized_roles: list[str] = []
        for role in raw_items:
            if not role:
                continue
            normalized = role.lower()
            if normalized not in _ALLOWED_ORG_ROLES:
                raise ValueError(f"unsupported mcp_dev_principal_role: {role}")
            if normalized not in normalized_roles:
                normalized_roles.append(normalized)
        return normalized_roles

    @field_validator(
        "mcp_capabilities_owner",
        "mcp_capabilities_admin",
        "mcp_capabilities_member",
        "mcp_capabilities_viewer",
        mode="before",
    )
    @classmethod
    def validate_mcp_capability_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("MCP capabilities must be a comma-separated string or list")

        normalized_capabilities: list[str] = []
        for capability in raw_items:
            if not capability:
                continue
            normalized = capability.lower()
            if not normalized.replace(".", "").replace("_", "").replace("-", "").isalnum():
                raise ValueError(f"invalid MCP capability identifier: {capability}")
            if normalized not in normalized_capabilities:
                normalized_capabilities.append(normalized)

        if not normalized_capabilities:
            raise ValueError("MCP capability list must contain at least one capability")
        return normalized_capabilities

    @field_validator("mcp_external_servers", mode="before")
    @classmethod
    def validate_external_mcp_servers(
        cls, value: object
    ) -> list[MCPExternalServerSettings] | list[dict[str, Any]]:
        if value is None:
            return []
        raw_items: list[object]
        if isinstance(value, str):
            normalized_text = value.strip()
            if not normalized_text:
                return []
            try:
                parsed = json.loads(normalized_text)
            except json.JSONDecodeError as exc:
                raise ValueError("mcp_external_servers must be valid JSON") from exc
            if not isinstance(parsed, list):
                raise ValueError("mcp_external_servers JSON value must be an array")
            raw_items = list(parsed)
        elif isinstance(value, list):
            raw_items = list(value)
        else:
            raise ValueError("mcp_external_servers must be a JSON array or list")

        normalized_items: list[MCPExternalServerSettings] = []
        seen_ids: set[str] = set()
        for item in raw_items:
            server_config = MCPExternalServerSettings.model_validate(item)
            if server_config.server_id in seen_ids:
                raise ValueError(f"duplicate external MCP server_id: {server_config.server_id}")
            seen_ids.add(server_config.server_id)
            normalized_items.append(server_config)
        return normalized_items


def validate_mcp_settings(settings: Settings) -> None:
    if settings.feature_enable_mcp and settings.mcp_transport == MCPTransport.stdio:
        if settings.environment in {Environment.production, Environment.staging}:
            raise ValueError(
                "mcp_transport=stdio is only allowed in development or test environments"
            )
        if settings.mcp_dev_principal_user_id is None:
            raise ValueError("mcp_dev_principal_user_id is required when mcp_transport=stdio")
        if settings.mcp_dev_principal_organization_id is None:
            raise ValueError(
                "mcp_dev_principal_organization_id is required when mcp_transport=stdio"
            )
        if not settings.mcp_dev_principal_roles:
            raise ValueError("mcp_dev_principal_roles is required when mcp_transport=stdio")

    if settings.feature_enable_mcp and settings.mcp_transport == MCPTransport.streamable_http:
        settings.mcp_http_host = settings.mcp_http_host.strip()
        if not settings.mcp_http_host:
            raise ValueError(
                "mcp_http_host must not be empty when mcp transport is streamable_http"
            )
        if not settings.mcp_require_bearer_auth and settings.environment in {
            Environment.production,
            Environment.staging,
        }:
            raise ValueError(
                "mcp_require_bearer_auth=false is only allowed in development or test environments"
            )
        if not settings.mcp_require_bearer_auth:
            if settings.mcp_dev_principal_user_id is None:
                raise ValueError(
                    "mcp_dev_principal_user_id is required when mcp_require_bearer_auth=false"
                )
            if settings.mcp_dev_principal_organization_id is None:
                raise ValueError(
                    "mcp_dev_principal_organization_id is required when mcp_require_bearer_auth=false"
                )
            if not settings.mcp_dev_principal_roles:
                raise ValueError(
                    "mcp_dev_principal_roles is required when mcp_require_bearer_auth=false"
                )

    if settings.feature_enable_external_mcp_connectors:
        enabled_servers = [server for server in settings.mcp_external_servers if server.enabled]
        if not enabled_servers:
            raise ValueError(
                "feature_enable_external_mcp_connectors=true requires at least one enabled mcp_external_servers entry"
            )
        if settings.environment in {Environment.production, Environment.staging}:
            for server in enabled_servers:
                if server.auth_type == MCPExternalAuthType.none:
                    raise ValueError(
                        "external MCP servers require auth_type=bearer or auth_type=header in staging/production"
                    )
