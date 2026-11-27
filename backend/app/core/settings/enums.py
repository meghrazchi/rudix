"""Enums and nested settings models shared by the Settings mixins."""

from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, field_validator, model_validator

_ALLOWED_ORG_ROLES = {"owner", "admin", "member", "viewer"}
_DEFAULT_MCP_VIEWER_CAPABILITIES = [
    "documents.read",
    "documents.chunks.read",
    "documents.summary.read",
    "documents.compare.read",
    "pipeline.read",
]
_DEFAULT_MCP_ELEVATED_CAPABILITIES = [
    *_DEFAULT_MCP_VIEWER_CAPABILITIES,
    "chat.answer",
]


class Environment(StrEnum):
    development = "development"
    test = "test"
    staging = "staging"
    production = "production"


class LogFormat(StrEnum):
    auto = "auto"
    json = "json"
    console = "console"


class AuthProvider(StrEnum):
    app = "app"
    clerk = "clerk"
    supabase = "supabase"
    internal_jwt = "internal_jwt"
    api_key = "api_key"


class RateLimitRedisFailureMode(StrEnum):
    open = "open"
    closed = "closed"


class QdrantDistance(StrEnum):
    cosine = "cosine"
    dot = "dot"
    euclid = "euclid"
    manhattan = "manhattan"


class MCPTransport(StrEnum):
    streamable_http = "streamable_http"
    stdio = "stdio"


class MCPExternalTransport(StrEnum):
    streamable_http = "streamable_http"


class MCPExternalAuthType(StrEnum):
    none = "none"
    bearer = "bearer"
    header = "header"


class RerankFallbackBehavior(StrEnum):
    original = "original"
    disabled = "disabled"


class ConnectorRolloutStage(StrEnum):
    off = "off"
    development = "development"
    staging = "staging"
    production = "production"
    all = "all"


class LangfuseRedactionMode(StrEnum):
    none = "none"
    inputs = "inputs"
    all = "all"


class MCPExternalServerSettings(BaseModel):
    server_id: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    enabled: bool = True
    transport: MCPExternalTransport = MCPExternalTransport.streamable_http
    base_url: AnyHttpUrl
    timeout_seconds: float = Field(default=8.0, ge=0.1, le=120.0)
    auth_type: MCPExternalAuthType = MCPExternalAuthType.none
    auth_token: SecretStr | None = None
    auth_header_name: str | None = Field(default=None, min_length=1, max_length=100)
    auth_header_value: SecretStr | None = None
    allow_tools: list[str] = Field(default_factory=list, max_length=200)
    allow_resources: list[str] = Field(default_factory=list, max_length=200)
    read_only_tools: list[str] = Field(default_factory=list, max_length=200)
    side_effect_tools: list[str] = Field(default_factory=list, max_length=200)
    required_roles: list[str] = Field(
        default_factory=lambda: ["owner", "admin"],
        max_length=4,
    )
    capability_prefix: str = Field(
        default="external_mcp",
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    expose_on_mcp_surface: bool = False
    approval_required_for_side_effect: bool = True
    budget_max_calls_per_run: int | None = Field(default=None, ge=1, le=500)
    budget_max_input_bytes: int | None = Field(default=None, ge=512, le=10_000_000)
    budget_max_output_bytes: int | None = Field(default=None, ge=512, le=10_000_000)
    budget_timeout_ms: int | None = Field(default=None, ge=100, le=300_000)
    budget_max_retry_attempts: int | None = Field(default=None, ge=0, le=10)

    @field_validator(
        "allow_tools",
        "allow_resources",
        "read_only_tools",
        "side_effect_tools",
        mode="before",
    )
    @classmethod
    def validate_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("value must be a comma-separated string or list")

        normalized_values: list[str] = []
        for item in raw_items:
            if not item:
                continue
            if item not in normalized_values:
                normalized_values.append(item)
        return normalized_values

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
            if not role:
                continue
            normalized = role.lower()
            if normalized not in _ALLOWED_ORG_ROLES:
                raise ValueError(f"unsupported required role: {role}")
            if normalized not in normalized_roles:
                normalized_roles.append(normalized)
        if not normalized_roles:
            raise ValueError("required_roles must contain at least one role")
        return normalized_roles

    @model_validator(mode="after")
    def validate_consistency(self) -> "MCPExternalServerSettings":
        if self.auth_type == MCPExternalAuthType.bearer:
            if self.auth_token is None or not self.auth_token.get_secret_value().strip():
                raise ValueError("auth_token is required when auth_type=bearer")
        if self.auth_type == MCPExternalAuthType.header:
            if self.auth_header_name is None:
                raise ValueError("auth_header_name is required when auth_type=header")
            if (
                self.auth_header_value is None
                or not self.auth_header_value.get_secret_value().strip()
            ):
                raise ValueError("auth_header_value is required when auth_type=header")

        if self.read_only_tools and self.side_effect_tools:
            overlap = set(self.read_only_tools).intersection(self.side_effect_tools)
            if overlap:
                overlap_text = ", ".join(sorted(overlap))
                raise ValueError(
                    f"tool names cannot appear in both read_only_tools and side_effect_tools: {overlap_text}"
                )

        if self.read_only_tools or self.side_effect_tools:
            allowlist = set(self.allow_tools)
            out_of_scope = {
                *[name for name in self.read_only_tools if name not in allowlist],
                *[name for name in self.side_effect_tools if name not in allowlist],
            }
            if out_of_scope:
                out_of_scope_text = ", ".join(sorted(out_of_scope))
                raise ValueError(
                    f"policy tools must also exist in allow_tools allowlist: {out_of_scope_text}"
                )
        return self


class ConnectorOAuthClientSettings(BaseModel):
    provider_key: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: SecretStr
    redirect_uri: AnyHttpUrl | None = None

    @field_validator("provider_key")
    @classmethod
    def validate_provider_key(cls, value: str) -> str:
        return value.strip().lower()
