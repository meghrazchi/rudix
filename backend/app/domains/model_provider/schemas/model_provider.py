from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Update request
# ---------------------------------------------------------------------------


class UpdateModelProviderSettingsRequest(BaseModel):
    """All fields are optional; only supplied fields are applied."""

    provider: str | None = Field(default=None, max_length=64)
    llm_model: str | None = Field(default=None, max_length=255)
    embedding_model: str | None = Field(default=None, max_length=255)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    fallback_model: str | None = Field(default=None, max_length=255)
    disabled_models: list[str] | None = Field(default=None, max_length=50)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        if value is not None:
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("provider must not be blank")
            return trimmed
        return value

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, value: str | None) -> str | None:
        if value is not None:
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("llm_model must not be blank")
            return trimmed
        return value

    @field_validator("embedding_model")
    @classmethod
    def validate_embedding_model(cls, value: str | None) -> str | None:
        if value is not None:
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("embedding_model must not be blank")
            return trimmed
        return value

    @field_validator("fallback_model")
    @classmethod
    def validate_fallback_model(cls, value: str | None) -> str | None:
        if value is not None:
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("fallback_model must not be blank")
            return trimmed
        return value

    @field_validator("disabled_models")
    @classmethod
    def validate_disabled_models(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned: list[str] = []
        for entry in value:
            trimmed = entry.strip()
            if not trimmed:
                raise ValueError("disabled_models entries must not be blank")
            if len(trimmed) > 255:
                raise ValueError("disabled_models entry exceeds 255 characters")
            cleaned.append(trimmed)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("disabled_models must not contain duplicates")
        return cleaned


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ModelProviderSettingsResponse(BaseModel):
    organization_id: str
    provider: str | None = None
    llm_model: str | None = None
    embedding_model: str | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    fallback_model: str | None = None
    disabled_models: list[str]
    # True when an LLM API key is present in the environment — never the key itself
    llm_key_configured: bool
    version: int
    updated_by_id: str | None = None
    updated_at: datetime


class EffectiveModelProviderPolicyResponse(BaseModel):
    """Merged view: org overrides applied on top of system defaults."""

    organization_id: str
    provider: str
    llm_model: str
    embedding_model: str
    max_tokens: int | None = None
    timeout_seconds: int
    max_retries: int
    fallback_model: str | None = None
    disabled_models: list[str]
    llm_key_configured: bool
    source: Literal["org_override", "system_default"]
    version: int


class ModelProviderChangeLogEntryResponse(BaseModel):
    entry_id: str
    organization_id: str
    version_number: int
    settings_snapshot: dict
    change_note: str | None = None
    changed_by_id: str | None = None
    created_at: datetime


class ModelProviderChangeLogResponse(BaseModel):
    items: list[ModelProviderChangeLogEntryResponse]
    total: int
