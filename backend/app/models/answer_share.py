from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

_ACCESS_MODE_ORG_ONLY = "org_only"
_ACCESS_MODE_SPECIFIC_USERS = "specific_users"


class AnswerShare(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-message (single Q+A turn) share link with optional password and user allowlist."""

    __tablename__ = "answer_shares"
    __table_args__ = (
        Index("idx_answer_shares_token", "token", unique=True),
        Index("idx_answer_shares_message", "chat_message_id"),
        Index("idx_answer_shares_org", "organization_id"),
    )

    chat_message_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    shared_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(86), nullable=False, unique=True)
    # "org_only" | "specific_users"
    access_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default=_ACCESS_MODE_ORG_ONLY
    )
    # JSON list of user-id strings; used only when access_mode == "specific_users"
    allowed_user_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Argon2 hash of the optional link password; None means no password required
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
