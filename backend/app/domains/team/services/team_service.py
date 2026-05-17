from __future__ import annotations

from uuid import uuid4

from app.domains.team.schemas.team import TeamMemberStatus
from app.models.organization_member import OrganizationMember
from app.models.user import User

_INVITED_SUBJECT_PREFIX = "invite::"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _display_name_from_email(email: str) -> str:
    local_part = email.split("@")[0].strip()
    if not local_part:
        return "Rudix User"
    chunks = [chunk for chunk in local_part.replace("_", "-").split("-") if chunk]
    if not chunks:
        return "Rudix User"
    return " ".join(chunk[:1].upper() + chunk[1:] for chunk in chunks)


class TeamService:
    @staticmethod
    def normalize_email(email: str) -> str:
        return _normalize_email(email)

    @staticmethod
    def invited_external_auth_id() -> str:
        return f"{_INVITED_SUBJECT_PREFIX}{uuid4()}"

    @staticmethod
    def display_name_for_email(email: str) -> str:
        return _display_name_from_email(email)

    @staticmethod
    def resolve_member_name(user: User | None) -> str:
        if user is None:
            return "Unknown user"
        if user.display_name and user.display_name.strip():
            return user.display_name.strip()
        return user.email

    @staticmethod
    def resolve_member_status(member: OrganizationMember) -> TeamMemberStatus:
        user = member.user
        if user is not None and user.external_auth_id.startswith(_INVITED_SUBJECT_PREFIX):
            return "invited"
        return "active"

