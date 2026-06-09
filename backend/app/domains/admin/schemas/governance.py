from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import OrganizationRole

_ALLOWED_ROLES = {role.value for role in OrganizationRole}


class MCPServerTransport(StrEnum):
    streamable_http = "streamable_http"


class MCPServerAuthType(StrEnum):
    none = "none"
    bearer = "bearer"
    header = "header"


class ExternalMCPServerPolicy(BaseModel):
    server_id: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    enabled: bool = True
    transport: MCPServerTransport = MCPServerTransport.streamable_http
    base_url: str = Field(min_length=8, max_length=600)
    auth_type: MCPServerAuthType = MCPServerAuthType.none
    auth_header_name: str | None = Field(default=None, min_length=1, max_length=100)
    auth_secret_ref: str | None = Field(default=None, min_length=1, max_length=255)
    allow_tools: list[str] = Field(default_factory=list, max_length=200)
    read_only_tools: list[str] = Field(default_factory=list, max_length=200)
    side_effect_tools: list[str] = Field(default_factory=list, max_length=200)
    required_roles: list[str] = Field(default_factory=lambda: ["owner", "admin"], max_length=4)
    expose_on_mcp_surface: bool = False
    approval_required_for_side_effect: bool = True

    @field_validator(
        "allow_tools",
        "read_only_tools",
        "side_effect_tools",
        mode="before",
    )
    @classmethod
    def validate_tool_names(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("tool list must be a comma-separated string or list")

        normalized: list[str] = []
        for item in raw_items:
            if not item:
                continue
            if item not in normalized:
                normalized.append(item)
        return normalized

    @field_validator("required_roles", mode="before")
    @classmethod
    def validate_required_roles(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("required_roles must be a comma-separated string or list")

        normalized_roles: list[str] = []
        for role in raw_items:
            normalized = role.lower()
            if not normalized:
                continue
            if normalized not in _ALLOWED_ROLES:
                raise ValueError(f"unsupported role: {role}")
            if normalized not in normalized_roles:
                normalized_roles.append(normalized)
        if not normalized_roles:
            raise ValueError("required_roles must contain at least one role")
        return normalized_roles

    @model_validator(mode="after")
    def validate_consistency(self) -> ExternalMCPServerPolicy:
        if self.auth_type is MCPServerAuthType.header and self.auth_header_name is None:
            raise ValueError("auth_header_name is required when auth_type=header")
        if self.auth_type in {MCPServerAuthType.bearer, MCPServerAuthType.header}:
            if self.auth_secret_ref is None:
                raise ValueError("auth_secret_ref is required for configured auth")

        if self.read_only_tools and self.side_effect_tools:
            overlap = set(self.read_only_tools).intersection(self.side_effect_tools)
            if overlap:
                overlap_text = ", ".join(sorted(overlap))
                raise ValueError(
                    f"tool names cannot appear in both read_only_tools and side_effect_tools: {overlap_text}"
                )
        return self


class GovernanceToolSummary(BaseModel):
    name: str
    capability: str
    effect_policy: str
    surfaces: list[str]
    required_roles: list[str]
    approval_required: bool


class GovernanceBudgetConfig(BaseModel):
    max_steps: int = Field(ge=1, le=200)
    max_tool_calls_per_run: int = Field(ge=1, le=500)
    max_tool_timeout_ms: int = Field(ge=100, le=300_000)
    max_tool_input_bytes: int = Field(ge=512, le=10_000_000)
    max_tool_output_bytes: int = Field(ge=512, le=10_000_000)
    max_tool_retry_attempts: int = Field(ge=0, le=10)
    max_total_tokens: int | None = Field(default=None, ge=1, le=50_000_000)
    max_total_cost_usd: Decimal | None = Field(default=None, ge=0, le=1_000_000)


class ProviderSecurityPolicy(BaseModel):
    """Provider routing and privacy controls (F225)."""

    local_only_mode: bool = False
    cloud_fallback_allowed: bool = True
    allowed_provider_profiles: list[str] = Field(default_factory=list)
    admin_only_model_selection: bool = True
    retention_warning_acknowledged: bool = False


class GovernancePolicyState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agentic_mode_enabled: bool
    mcp_exposure_enabled: bool
    allow_side_effect_tools: bool
    allowed_tool_names: list[str] = Field(default_factory=list)
    budgets: GovernanceBudgetConfig
    external_mcp_servers: list[ExternalMCPServerPolicy] = Field(default_factory=list)
    provider_security: ProviderSecurityPolicy = Field(
        default_factory=ProviderSecurityPolicy
    )


class GovernanceMCPStatus(BaseModel):
    feature_enable_mcp: bool
    mcp_transport: str
    mcp_http_path: str
    mcp_http_host: str
    mcp_http_port: int
    mcp_auth_required: bool
    mcp_rate_limit_enabled: bool
    feature_enable_external_mcp_connectors: bool
    configured_global_external_servers: int


class GovernancePolicyResponse(BaseModel):
    organization_id: str
    policy: GovernancePolicyState
    mcp_status: GovernanceMCPStatus
    tool_catalog: list[GovernanceToolSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    policy_updated_at: datetime | None = None
    policy_updated_by_user_id: str | None = None


class GovernancePolicyUpdateRequest(BaseModel):
    agentic_mode_enabled: bool | None = None
    mcp_exposure_enabled: bool | None = None
    allow_side_effect_tools: bool | None = None
    allowed_tool_names: list[str] | None = Field(default=None, max_length=400)
    budgets: GovernanceBudgetConfig | None = None
    external_mcp_servers: list[ExternalMCPServerPolicy] | None = Field(
        default=None,
        max_length=30,
    )
    side_effect_warning_acknowledged: bool = False
    # F225 — provider security fields
    provider_security: ProviderSecurityPolicy | None = None
    cloud_fallback_warning_acknowledged: bool = False

    @field_validator("allowed_tool_names")
    @classmethod
    def dedupe_allowed_tool_names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            candidate = item.strip()
            if not candidate:
                continue
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized

    @model_validator(mode="after")
    def validate_update_payload(self) -> GovernancePolicyUpdateRequest:
        if (
            self.allowed_tool_names is not None
            and len(self.allowed_tool_names) == 0
            and self.allow_side_effect_tools is True
            and not self.side_effect_warning_acknowledged
        ):
            raise ValueError(
                "side_effect_warning_acknowledged must be true when enabling side effects"
            )
        return self


class GovernancePolicyUpdateResponse(BaseModel):
    organization_id: str
    policy: GovernancePolicyState
    warnings: list[str] = Field(default_factory=list)
    updated_at: datetime
    updated_by_user_id: str | None = None
    audit_recorded: bool
    changed_fields: list[str] = Field(default_factory=list)
