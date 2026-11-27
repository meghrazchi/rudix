"""Cached auth principal snapshot (R04-05).

The snapshot holds what ``AppAuthProvider.authenticate`` needs from the database: the user's
active flag, email, default organisation, memberships, and the state of the token's session
row. It is cached under the user scope keyed by session id, so any membership, user, or
session-revocation write bumps the user version and the next request reloads it. A revoked
session is never cached: the loader raises before a snapshot exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, TypeAdapter

from app.models.auth_session import AuthRefreshSession
from app.models.user import User

_REQUEST_STATE_ATTR = "auth_principal_snapshot"


class MembershipSnapshot(BaseModel):
    role: str
    custom_role_id: UUID | None = None


class SessionSnapshot(BaseModel):
    """The token's active session row; ``present`` is false when no row is stored."""

    present: bool
    owner_user_id: UUID | None = None
    expires_at: datetime | None = None

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= (now or datetime.now(tz=UTC))


class PrincipalSnapshot(BaseModel):
    user_id: UUID
    is_active: bool
    email: str | None = None
    default_organization_id: UUID | None = None
    # Insertion order is the membership order; the provider's fallback picks the first.
    memberships: dict[str, MembershipSnapshot]
    session: SessionSnapshot

    def custom_role_id_for(self, organization_id: str) -> UUID | None:
        membership = self.memberships.get(organization_id)
        return membership.custom_role_id if membership is not None else None


PRINCIPAL_SNAPSHOT_ADAPTER: TypeAdapter[PrincipalSnapshot] = TypeAdapter(PrincipalSnapshot)


def build_snapshot(user: User, session_record: AuthRefreshSession | None) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=user.id,
        is_active=user.is_active,
        email=user.email,
        default_organization_id=user.organization_id,
        memberships={
            str(membership.organization_id): MembershipSnapshot(
                role=membership.role,
                custom_role_id=membership.custom_role_id,
            )
            for membership in user.memberships
        },
        session=SessionSnapshot(
            present=session_record is not None,
            owner_user_id=session_record.user_id if session_record is not None else None,
            expires_at=session_record.expires_at if session_record is not None else None,
        ),
    )


def store_request_snapshot(request: Request, snapshot: PrincipalSnapshot) -> None:
    setattr(request.state, _REQUEST_STATE_ATTR, snapshot)


def request_snapshot(request: Request, *, user_id: str) -> PrincipalSnapshot | None:
    """The snapshot this request authenticated with, if it belongs to ``user_id``."""
    snapshot = getattr(request.state, _REQUEST_STATE_ATTR, None)
    if isinstance(snapshot, PrincipalSnapshot) and str(snapshot.user_id) == user_id:
        return snapshot
    return None
