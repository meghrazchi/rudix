from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── Domain verification ───────────────────────────────────────────────────────

class InitiateDomainVerificationRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        cleaned = value.strip().lower().lstrip("@")
        if not cleaned or "." not in cleaned:
            raise ValueError("domain must be a valid email domain (e.g. company.com)")
        return cleaned


class DomainVerificationResponse(BaseModel):
    id: str
    organization_id: str
    domain: str
    status: Literal["pending", "verified", "failed"]
    verification_token: str
    txt_record_name: str
    txt_record_value: str
    verified_at: datetime | None
    last_checked_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class DomainCheckResponse(BaseModel):
    id: str
    domain: str
    status: Literal["pending", "verified", "failed"]
    verified_at: datetime | None
    last_checked_at: datetime | None
    failure_reason: str | None


# ── SCIM config ───────────────────────────────────────────────────────────────

class SCIMConfigResponse(BaseModel):
    id: str
    organization_id: str
    enabled: bool
    token_hint: str
    scim_base_url: str
    last_sync_at: datetime | None
    last_sync_error: str | None
    provisioned_count: int
    deprovisioned_count: int
    created_at: datetime
    updated_at: datetime


class SCIMEnableResponse(BaseModel):
    """Returned once when SCIM is enabled or token is rotated. Token not shown again."""
    config: SCIMConfigResponse
    bearer_token: str


# ── SCIM 2.0 protocol types ───────────────────────────────────────────────────

class SCIM2Email(BaseModel):
    value: str
    primary: bool = True
    type: str = "work"


class SCIM2Name(BaseModel):
    formatted: str | None = None
    givenName: str | None = None
    familyName: str | None = None


class SCIM2UserRequest(BaseModel):
    schemas: list[str] = Field(
        default=["urn:ietf:params:scim:schemas:core:2.0:User"]
    )
    externalId: str | None = None
    userName: str
    displayName: str | None = None
    name: SCIM2Name | None = None
    emails: list[SCIM2Email] = Field(default_factory=list)
    active: bool = True


class SCIM2PatchOp(BaseModel):
    schemas: list[str] = Field(
        default=["urn:ietf:params:scim:api:messages:2.0:PatchOp"]
    )
    Operations: list[dict]


class SCIM2UserResponse(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    id: str
    externalId: str | None
    userName: str
    displayName: str | None
    active: bool
    emails: list[SCIM2Email]
    meta: dict


class SCIM2ListResponse(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
    totalResults: int
    startIndex: int
    itemsPerPage: int
    Resources: list[SCIM2UserResponse]


class SCIM2ErrorResponse(BaseModel):
    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:Error"]
    status: str
    detail: str
