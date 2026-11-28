"""Per-organisation login policy (0.9.0, R09-02).

No row means today's behaviour: MFA is not required. ``mfa_required_since`` starts the
grace period (``mfa_grace_period_days``) after which members without a factor are blocked.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class OrgLoginPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "org_login_policies"
    __table_args__ = (
        CheckConstraint(
            "mfa_grace_period_days >= 0 AND mfa_grace_period_days <= 90",
            name="mfa_grace_period_days_range",
        ),
        Index("idx_org_login_policies_updated_by", "updated_by_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    mfa_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    mfa_grace_period_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7, server_default="7"
    )
    mfa_required_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
