from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.domains.chat.schemas.chat import SourceScopeRequest

BotProvider = Literal["slack", "teams"]
BotInstallationStatus = Literal["enabled", "disabled"]
BotUserMappingStatus = Literal["active", "disabled"]


def _strip_required(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("value must not be blank")
    return trimmed


def _ensure_safe_config(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    blocked_keys = _secret_like_config_keys(value)
    if blocked_keys:
        raise ValueError(
            "config must not contain secrets; use the credential endpoint for bot tokens"
        )
    return value


def _secret_like_config_keys(value: object, *, prefix: str = "") -> list[str]:
    blocked_fragments = ("token", "secret", "password", "credential", "authorization")
    if isinstance(value, dict):
        blocked: list[str] = []
        for key, nested_value in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if any(fragment in key_text.lower() for fragment in blocked_fragments):
                blocked.append(path)
            blocked.extend(_secret_like_config_keys(nested_value, prefix=path))
        return sorted(blocked)
    if isinstance(value, list):
        blocked = []
        for index, item in enumerate(value):
            path = f"{prefix}[{index}]"
            blocked.extend(_secret_like_config_keys(item, prefix=path))
        return sorted(blocked)
    return []


class BotInstallationCreateRequest(BaseModel):
    provider: BotProvider
    external_workspace_id: str = Field(min_length=1, max_length=255)
    external_tenant_id: str | None = Field(default=None, max_length=255)
    external_team_id: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    status: BotInstallationStatus = "enabled"
    default_source_scope: SourceScopeRequest | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("external_workspace_id")
    @classmethod
    def validate_workspace_id(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("external_tenant_id", "external_team_id", "display_name")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _ensure_safe_config(value) or {}


class BotInstallationUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    status: BotInstallationStatus | None = None
    default_source_scope: SourceScopeRequest | None = None
    config: dict[str, Any] | None = None

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _ensure_safe_config(value)


class BotUserMappingUpsertRequest(BaseModel):
    external_user_id: str = Field(min_length=1, max_length=255)
    rudix_user_id: str = Field(min_length=1, max_length=64)
    external_email: str | None = Field(default=None, max_length=255)
    status: BotUserMappingStatus = "active"

    @field_validator("external_user_id", "rudix_user_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("external_email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip().lower()
        return trimmed or None


class BotCredentialUpdateRequest(BaseModel):
    bot_token: SecretStr
    scopes: list[str] = Field(default_factory=list, max_length=50)
    expires_at: datetime | None = None

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("bot_token must not be blank")
        return value

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            cleaned = str(item).strip()
            if not cleaned:
                continue
            if cleaned not in normalized:
                normalized.append(cleaned)
        return normalized


class BotCredentialResponse(BaseModel):
    configured: bool
    fingerprint: str | None = None
    encryption_key_id: str | None = None
    encryption_algorithm: str | None = None
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class BotSlackOAuthStartRequest(BaseModel):
    scopes: list[str] | None = Field(default=None, max_length=50)
    redirect_uri: str | None = Field(default=None, max_length=2048)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            cleaned = str(item).strip()
            if not cleaned:
                continue
            if cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @field_validator("redirect_uri")
    @classmethod
    def validate_redirect_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class BotSlackOAuthStartResponse(BaseModel):
    authorization_url: str
    state: str
    redirect_uri: str
    scopes: list[str]
    expires_in_seconds: int


class BotInstallationResponse(BaseModel):
    id: str
    organization_id: str
    provider: BotProvider
    external_workspace_id: str
    external_tenant_id: str | None = None
    external_team_id: str | None = None
    display_name: str | None = None
    status: BotInstallationStatus
    default_source_scope: SourceScopeRequest | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    credential: BotCredentialResponse = Field(
        default_factory=lambda: BotCredentialResponse(configured=False)
    )
    created_at: datetime
    updated_at: datetime


class BotSlackOAuthCallbackResponse(BaseModel):
    ok: bool
    installation: BotInstallationResponse
    credential: BotCredentialResponse


class BotInstallationListResponse(BaseModel):
    items: list[BotInstallationResponse]
    total: int


class BotUserMappingResponse(BaseModel):
    id: str
    installation_id: str
    organization_id: str
    rudix_user_id: str
    external_user_id: str
    external_email: str | None = None
    status: BotUserMappingStatus
    created_at: datetime
    updated_at: datetime


class BotUserMappingListResponse(BaseModel):
    items: list[BotUserMappingResponse]
    total: int


class BotCitationLinkResponse(BaseModel):
    label: str
    document_id: str
    chunk_id: str
    filename: str | None = None
    page_number: int | None = None
    url: str


class BotErrorResponse(BaseModel):
    code: str
    message: str


class BotAskResponse(BaseModel):
    ok: bool
    provider: BotProvider
    response_type: Literal["in_channel", "ephemeral"] = "ephemeral"
    text: str
    loading_text: str | None = None
    thread_id: str | None = None
    chat_session_id: str | None = None
    message_id: str | None = None
    not_found: bool = False
    citations: list[BotCitationLinkResponse] = Field(default_factory=list)
    error: BotErrorResponse | None = None
