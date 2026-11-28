from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class AuthRefreshSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "auth_refresh_sessions"
    __table_args__ = (
        Index("idx_auth_refresh_sessions_user", "user_id", "created_at"),
        Index("idx_auth_refresh_sessions_org", "organization_id", "created_at"),
        Index("idx_auth_refresh_sessions_session", "session_id"),
        Index("idx_auth_refresh_sessions_token_hash", "refresh_token_hash"),
        Index("idx_auth_refresh_sessions_expires", "expires_at"),
        Index("idx_auth_refresh_sessions_revoked", "revoked_at"),
        # 0.9.0 (R09-02, migration 20261129_0002).
        CheckConstraint("auth_method IN ('password', 'sso')", name="auth_method_allowed"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    refresh_token_jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 0.9.0 (R09-02, migration 20261129_0002): how the session was opened, and when its
    # holder last passed an MFA challenge (NULL: never in this session).
    auth_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="password", server_default="password"
    )
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization")
    user = relationship("User")
