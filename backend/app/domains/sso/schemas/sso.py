from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SSOConfigResponse(BaseModel):
    id: str
    organization_id: str
    sso_type: str
    domain: str
    enabled: bool
    idp_metadata_url: str | None
    sp_entity_id: str
    sp_acs_url: str
    idp_entity_id: str | None
    idp_sso_url: str | None
    attribute_mapping: dict
    last_test_at: datetime | None
    last_test_result: str | None
    created_at: datetime
    updated_at: datetime


class UpsertSSOConfigRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    sso_type: Literal["saml", "oidc"] = "saml"
    enabled: bool = False
    idp_metadata_url: str | None = Field(default=None, max_length=2048)
    idp_metadata_xml: str | None = Field(default=None, max_length=65536)
    idp_sso_url: str | None = Field(default=None, max_length=2048)
    idp_entity_id: str | None = Field(default=None, max_length=1024)
    idp_certificate: str | None = Field(default=None, max_length=65536)
    attribute_mapping: dict = Field(default_factory=dict)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("domain must not be empty")
        # strip leading @ if someone passes "@company.com"
        if cleaned.startswith("@"):
            cleaned = cleaned[1:]
        if not cleaned or "." not in cleaned:
            raise ValueError("domain must be a valid email domain (e.g. company.com)")
        return cleaned


class TestConnectionRequest(BaseModel):
    idp_metadata_url: str | None = Field(default=None, max_length=2048)
    idp_metadata_xml: str | None = Field(default=None, max_length=65536)
    idp_sso_url: str | None = Field(default=None, max_length=2048)


class TestConnectionResponse(BaseModel):
    success: bool
    result: Literal["success", "failure"]
    detail: str
    checked_at: datetime


class SSODiscoverRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class SSODiscoverResponse(BaseModel):
    sso_enabled: bool
    sso_type: str | None
    redirect_url: str | None
    domain: str | None


class SSOMetadataResponse(BaseModel):
    sp_entity_id: str
    sp_acs_url: str
    organization_id: str
