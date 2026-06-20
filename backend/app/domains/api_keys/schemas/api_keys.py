from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

VALID_SCOPES = frozenset(
    {
        "documents:read",
        "documents:write",
        "chat:write",
        "evaluations:run",
        "webhooks:manage",
        "connectors:manage",
    }
)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: list[str]) -> list[str]:
        unknown = [s for s in values if s not in VALID_SCOPES]
        if unknown:
            raise ValueError(f"unknown scopes: {unknown}")
        return list(dict.fromkeys(values))


class UpdateApiKeyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class ApiKeyResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str | None
    key_prefix: str
    scopes: list[str]
    status: str
    expires_at: datetime | None
    last_used_at: datetime | None
    created_by_id: str | None
    created_at: datetime
    updated_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only at creation time — contains the raw key shown exactly once."""

    raw_key: str


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyResponse]
    total: int
