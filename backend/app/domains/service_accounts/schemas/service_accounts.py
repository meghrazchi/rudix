from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

VALID_SCOPES = frozenset({
    "documents:read",
    "documents:write",
    "chat:write",
    "evaluations:run",
    "webhooks:manage",
    "connectors:manage",
})

VALID_ENVIRONMENTS = frozenset({"production", "staging", "ci", "development"})


class CreateServiceAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    environment: str = Field(default="production")
    scopes: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        if value not in VALID_ENVIRONMENTS:
            raise ValueError(f"environment must be one of {sorted(VALID_ENVIRONMENTS)}")
        return value

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: list[str]) -> list[str]:
        unknown = [s for s in values if s not in VALID_SCOPES]
        if unknown:
            raise ValueError(f"unknown scopes: {unknown}")
        return list(dict.fromkeys(values))


class UpdateServiceAccountRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    environment: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in VALID_ENVIRONMENTS:
            raise ValueError(f"environment must be one of {sorted(VALID_ENVIRONMENTS)}")
        return value


class ServiceAccountResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str | None
    environment: str
    scopes: list[str]
    is_active: bool
    last_used_at: datetime | None
    created_by_id: str | None
    created_at: datetime
    updated_at: datetime


class ServiceAccountListResponse(BaseModel):
    items: list[ServiceAccountResponse]
    total: int


# ── Token schemas ─────────────────────────────────────────────────────────────

class CreateServiceAccountTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class ServiceAccountTokenResponse(BaseModel):
    id: str
    service_account_id: str
    name: str
    token_prefix: str
    status: str
    expires_at: datetime | None
    last_used_at: datetime | None
    created_by_id: str | None
    created_at: datetime
    updated_at: datetime


class ServiceAccountTokenCreatedResponse(ServiceAccountTokenResponse):
    """Returned only at token-creation time — raw token shown exactly once."""
    raw_token: str


class ServiceAccountTokenListResponse(BaseModel):
    items: list[ServiceAccountTokenResponse]
    total: int
