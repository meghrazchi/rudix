from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class OrganizationInvitationResponse(BaseModel):
    invitation_id: str
    organization_id: str
    email: str
    role: str
    status: str
    expires_at: datetime
    invited_by_name: str | None
    resend_count: int
    last_sent_at: datetime | None
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrganizationInvitationListResponse(BaseModel):
    items: list[OrganizationInvitationResponse]
    total: int
    limit: int
    offset: int


class ResendInvitationResponse(BaseModel):
    invitation_id: str
    resent: bool


class RevokeInvitationResponse(BaseModel):
    invitation_id: str
    revoked: bool


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("token must not be empty")
        return stripped


class AcceptInvitationResponse(BaseModel):
    accepted: bool
    email: str
    role: str
    organization_name: str | None
