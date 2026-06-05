from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ConnectorAuthType


class OAuthCredentialPayload(BaseModel):
    auth_type: Literal[ConnectorAuthType.oauth2] = ConnectorAuthType.oauth2
    access_token: str = Field(min_length=1)
    refresh_token: str | None = Field(default=None, min_length=1)
    token_type: str = Field(default="Bearer", min_length=1, max_length=64)
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    provider_account_id: str | None = Field(default=None, max_length=512)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_scope in value:
            scope = raw_scope.strip()
            if scope and scope not in normalized:
                normalized.append(scope)
        return normalized


class ApiTokenCredentialPayload(BaseModel):
    auth_type: Literal[ConnectorAuthType.api_token] = ConnectorAuthType.api_token
    api_token: str = Field(min_length=1)
    token_label: str | None = Field(default=None, max_length=255)


class ServiceAccountCredentialPayload(BaseModel):
    auth_type: Literal[ConnectorAuthType.service_account] = ConnectorAuthType.service_account
    service_account_json: dict[str, Any] = Field(min_length=1)


ConnectorCredentialPayload = (
    OAuthCredentialPayload | ApiTokenCredentialPayload | ServiceAccountCredentialPayload
)


class OAuthTokenResponse(BaseModel):
    access_token: str = Field(min_length=1)
    refresh_token: str | None = Field(default=None, min_length=1)
    token_type: str = Field(default="Bearer", min_length=1, max_length=64)
    expires_in: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    scope: str | None = None
    scopes: list[str] | None = None
    provider_account_id: str | None = Field(default=None, max_length=512)

    def resolved_scopes(self, fallback_scopes: list[str]) -> list[str]:
        if self.scopes is not None:
            raw_scopes = self.scopes
        elif self.scope is not None:
            raw_scopes = self.scope.split(" ")
        else:
            raw_scopes = fallback_scopes
        normalized: list[str] = []
        for raw_scope in raw_scopes:
            scope = raw_scope.strip()
            if scope and scope not in normalized:
                normalized.append(scope)
        return normalized
