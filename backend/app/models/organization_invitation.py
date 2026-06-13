from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

_STATUS_CHECK = "status IN ('pending', 'accepted', 'expired', 'revoked')"
_ROLE_CHECK = (
    "role IN ("
    "'admin', 'member', 'viewer', "
    "'reviewer', 'security_admin', 'billing_admin', 'developer'"
    ")"
)


class OrganizationInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="org_invitations_status_allowed"),
        CheckConstraint(_ROLE_CHECK, name="org_invitations_role_allowed"),
        Index("idx_org_invitations_org_status", "organization_id", "status"),
        Index("idx_org_invitations_email_org", "email", "organization_id"),
        Index("idx_org_invitations_token_hash", "token_hash"),
        Index("idx_org_invitations_expires", "expires_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resend_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    member_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organization_members.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization")
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
    accepted_by = relationship("User", foreign_keys=[accepted_by_user_id])
    revoked_by = relationship("User", foreign_keys=[revoked_by_user_id])
    member = relationship("OrganizationMember", foreign_keys=[member_id])
