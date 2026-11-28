"""Multi-factor authentication factors and recovery codes (0.9.0, R09-02).

User-scoped (no ``organization_id``): a factor protects the user in every organisation.
The TOTP secret is stored encrypted (``encrypted_secret`` with key id and algorithm); recovery
codes are stored as keyed hashes only and are single-use (``used_at``).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

MFA_FACTOR_TYPES: tuple[str, ...] = ("totp",)
MFA_FACTOR_STATUSES: tuple[str, ...] = ("pending", "active")


class UserMfaFactor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_mfa_factors"
    __table_args__ = (
        CheckConstraint("factor_type IN ('totp')", name="factor_type_allowed"),
        CheckConstraint("status IN ('pending', 'active')", name="status_allowed"),
        # At most one active factor per type and user; pending enrolments may coexist.
        Index(
            "uq_user_mfa_factors_user_type_active",
            "user_id",
            "factor_type",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    factor_type: Mapped[str] = mapped_column(String(16), nullable=False, default="totp")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    secret_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    secret_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Last accepted TOTP time step; a code for the same or an earlier step is refused.
    last_used_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserMfaRecoveryCode(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_mfa_recovery_codes"
    __table_args__ = (Index("idx_user_mfa_recovery_codes_user", "user_id"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    factor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("user_mfa_factors.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
