"""Single-use account tokens (0.9.0, R09-01, R09-02, R09-10).

One table holds every short-lived, single-use secret the account flows hand out: email
verification and password reset links, MFA challenge and enrolment handles, step-up tokens,
and SAML request and assertion ids (replay detection). Only the SHA-256 hex digest of the
raw token is stored; ``metadata`` never holds secrets or email bodies.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import UUIDPrimaryKeyMixin

ONE_TIME_TOKEN_PURPOSES: tuple[str, ...] = (
    "email_verification",
    "password_reset",
    "mfa_challenge",
    "mfa_enrolment",
    "step_up",
    "saml_request",
    "saml_assertion",
)
_PURPOSES_SQL = ", ".join(f"'{purpose}'" for purpose in ONE_TIME_TOKEN_PURPOSES)


class AuthOneTimeToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_one_time_tokens"
    __table_args__ = (
        CheckConstraint(f"purpose IN ({_PURPOSES_SQL})", name="purpose_allowed"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        Index("idx_auth_one_time_tokens_user_purpose", "user_id", "purpose"),
        Index("idx_auth_one_time_tokens_expires", "expires_at"),
        Index("idx_auth_one_time_tokens_purpose_consumed", "purpose", "consumed_at"),
    )

    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ``metadata`` is reserved on declarative classes; the column keeps the plain name.
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
