from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import (
    ConnectorAuthType,
    ConnectorCapability,
    ExternalItemType,
    ExternalItemVisibility,
)


class ProviderRateLimit(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    max_requests: int = Field(ge=1)
    window_seconds: int = Field(ge=1)
    burst: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _trim_non_blank(value, "name")


class ProviderExportFormat(BaseModel):
    format: str = Field(min_length=1, max_length=64)
    mime_type: str = Field(min_length=1, max_length=255)

    @field_validator("format", "mime_type")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        return _trim_non_blank(value, "export format field")


class ProviderCapabilities(BaseModel):
    auth_type: ConnectorAuthType
    capabilities: frozenset[ConnectorCapability] = Field(default_factory=frozenset)
    rate_limits: tuple[ProviderRateLimit, ...] = Field(default_factory=tuple)
    export_formats: tuple[ProviderExportFormat, ...] = Field(default_factory=tuple)
    max_page_size: int | None = Field(default=None, ge=1, le=10_000)
    notes: str | None = Field(default=None, max_length=4000)

    def supports(self, capability: ConnectorCapability) -> bool:
        return capability in self.capabilities


class ProviderOAuthConfig(BaseModel):
    authorization_endpoint: str = Field(min_length=1, max_length=2048)
    token_endpoint: str = Field(min_length=1, max_length=2048)
    revoke_endpoint: str | None = Field(default=None, min_length=1, max_length=2048)
    # RFC 7591 token endpoint auth method. Use "client_secret_basic" for providers
    # (e.g. Notion) that require HTTP Basic Auth instead of body params.
    token_endpoint_auth_method: Literal["client_secret_post", "client_secret_basic"] = Field(
        default="client_secret_post"
    )
    default_scopes: tuple[str, ...] = Field(default_factory=tuple)
    required_scopes: tuple[str, ...] = Field(default_factory=tuple)
    optional_scopes: tuple[str, ...] = Field(default_factory=tuple)
    additional_authorization_params: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "default_scopes",
        "required_scopes",
        "optional_scopes",
        mode="before",
    )
    @classmethod
    def validate_scope_tuple(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            raw_values = [value]
        elif isinstance(value, (list, tuple, set)):
            raw_values = list(value)
        else:
            raise ValueError("OAuth scopes must be a string or list")
        normalized: list[str] = []
        for raw_value in raw_values:
            scope = str(raw_value).strip()
            if not scope:
                continue
            if scope not in normalized:
                normalized.append(scope)
        return tuple(normalized)

    @field_validator("additional_authorization_params")
    @classmethod
    def validate_authorization_params(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = raw_key.strip()
            param_value = raw_value.strip()
            if not key or not param_value:
                raise ValueError("authorization params must not contain blank keys or values")
            normalized[key] = param_value
        return normalized

    @model_validator(mode="after")
    def validate_scope_policy(self) -> ProviderOAuthConfig:
        allowed_scopes = set(self.required_scopes).union(self.optional_scopes)
        missing_default = set(self.default_scopes).difference(allowed_scopes)
        if missing_default:
            raise ValueError("default_scopes must be included in required or optional scopes")
        missing_required = set(self.required_scopes).difference(self.default_scopes)
        if missing_required:
            raise ValueError("default_scopes must include every required scope")
        return self

    @property
    def allowed_scopes(self) -> frozenset[str]:
        return frozenset({*self.required_scopes, *self.optional_scopes})


class ProviderRegistration(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    capabilities: ProviderCapabilities
    config_schema: dict[str, Any] = Field(default_factory=dict)
    oauth: ProviderOAuthConfig | None = None
    enabled_by_default: bool = Field(default=True)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        trimmed = _trim_non_blank(value, "key").lower()
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
        if any(character not in allowed for character in trimmed):
            raise ValueError(
                "key may contain only lowercase letters, digits, dashes, and underscores"
            )
        return trimmed

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _trim_non_blank(value, "display_name")

    @field_validator("config_schema")
    @classmethod
    def validate_config_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        schema_type = value.get("type")
        if schema_type is not None and schema_type != "object":
            raise ValueError("config_schema must describe a JSON object")
        return value


class NormalizedExternalItem(BaseModel):
    organization_id: UUID
    provider_key: str = Field(min_length=1, max_length=64)
    provider_item_id: str = Field(min_length=1, max_length=1024)
    item_type: ExternalItemType
    title: str = Field(min_length=1, max_length=1024)
    source_url: str = Field(min_length=1, max_length=2048)
    content_hash: str = Field(min_length=64, max_length=64)
    updated_at: datetime
    sync_version: int = Field(ge=1)
    connection_id: UUID | None = None
    external_source_id: UUID | None = None
    collection_id: UUID | None = None
    provider_parent_id: str | None = Field(default=None, max_length=1024)
    root_provider_item_id: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=255)
    visibility: ExternalItemVisibility = ExternalItemVisibility.org_wide
    acl_hash: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_key")
    @classmethod
    def validate_provider_key(cls, value: str) -> str:
        return _trim_non_blank(value, "provider_key").lower()

    @field_validator("provider_item_id", "title")
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        return _trim_non_blank(value, "required field")

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        trimmed = _trim_non_blank(value, "source_url")
        if not (trimmed.startswith("https://") or trimmed.startswith("http://")):
            raise ValueError("source_url must be an HTTP(S) URL")
        return trimmed

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        trimmed = value.strip().lower()
        if len(trimmed) != 64 or any(character not in "0123456789abcdef" for character in trimmed):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return trimmed

    @field_validator("provider_parent_id", "root_provider_item_id", "mime_type", "acl_hash")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def validate_item_relationships(self) -> NormalizedExternalItem:
        if self.item_type in {ExternalItemType.comment, ExternalItemType.attachment}:
            if self.provider_parent_id is None:
                raise ValueError("comments and attachments require provider_parent_id")
        if self.visibility == ExternalItemVisibility.collection and self.collection_id is None:
            raise ValueError("collection visibility requires collection_id")
        return self


def _trim_non_blank(value: str, field_name: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{field_name} must not be blank")
    return trimmed
