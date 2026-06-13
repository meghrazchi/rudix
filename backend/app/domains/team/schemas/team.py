from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import OrganizationRole

TeamInviteRole = Literal[
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
    OrganizationRole.reviewer.value,
    OrganizationRole.developer.value,
    OrganizationRole.security_admin.value,
    OrganizationRole.billing_admin.value,
]
TeamMemberStatus = Literal["active", "invited", "disabled", "suspended", "unknown"]


class TeamMemberResponse(BaseModel):
    member_id: str
    user_id: str | None
    name: str
    email: str
    role: str
    custom_role_id: str | None = None
    status: TeamMemberStatus
    created_at: datetime | None
    updated_at: datetime | None


class TeamMemberDetailResponse(TeamMemberResponse):
    is_active: bool
    provisioned_by: str


class TeamMemberListResponse(BaseModel):
    items: list[TeamMemberResponse]
    total: int
    limit: int
    offset: int


class InviteTeamMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: TeamInviteRole = OrganizationRole.member.value
    name: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("email must be a valid address")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None


class InviteTeamMemberResponse(BaseModel):
    member: TeamMemberResponse
    invited: bool


class UpdateTeamMemberRoleRequest(BaseModel):
    role: TeamInviteRole | None = None
    custom_role_id: str | None = None


class TeamMemberRemoveResponse(BaseModel):
    removed: bool = True


class SetMemberPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class SetMemberPasswordResponse(BaseModel):
    member_id: str
    password_set: bool = True
