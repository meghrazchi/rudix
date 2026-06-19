from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class ServiceAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "service_accounts"
    __table_args__ = (
        Index("idx_service_accounts_org_id", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. "production", "staging", "ci", "development"
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="production")
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization")
    created_by = relationship("User", foreign_keys=[created_by_id])
    tokens = relationship(
        "ServiceAccountToken",
        back_populates="service_account",
        cascade="all, delete-orphan",
    )


class ServiceAccountToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "service_account_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_service_account_tokens_token_hash"),
        Index("idx_service_account_tokens_account_id", "service_account_id"),
        Index("idx_service_account_tokens_token_hash", "token_hash"),
        Index("idx_service_account_tokens_org_id", "organization_id"),
    )

    service_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("service_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized for fast auth lookup without joining service_accounts.
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # First 16 chars of raw token — safe to display in UI.
    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    # SHA-256 hex digest of the full raw token.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    service_account = relationship("ServiceAccount", back_populates="tokens")
    created_by = relationship("User", foreign_keys=[created_by_id])
