from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import OrganizationRole

TeamInviteRole = Literal[
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
]
TeamMemberStatus = Literal["active", "invited", "disabled", "suspended", "unknown"]


class TeamMemberResponse(BaseModel):
    member_id: str
    user_id: str | None
    name: str
    email: str
    role: str
    status: TeamMemberStatus
    created_at: datetime | None
    updated_at: datetime | None


class TeamMemberListResponse(BaseModel):
    items: list[TeamMemberResponse]
    total: int
    limit: int
    offset: int


class InviteTeamMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: TeamInviteRole = OrganizationRole.member.value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("email must be a valid address")
        return normalized


class InviteTeamMemberResponse(BaseModel):
    member: TeamMemberResponse
    invited: bool


class UpdateTeamMemberRoleRequest(BaseModel):
    role: TeamInviteRole


class TeamMemberRemoveResponse(BaseModel):
    removed: bool = True

