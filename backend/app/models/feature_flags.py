from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import UUIDPrimaryKeyMixin


class OrgFeatureFlagOverride(UUIDPrimaryKeyMixin, Base):
    """Stores per-organization overrides for feature flags.

    Resolution precedence: env default (settings.feature_enable_*) → this override.
    Admins/owners can suppress an env-enabled flag or enable an env-disabled one.
    """

    __tablename__ = "org_feature_flag_overrides"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "flag_name",
            name="uq_org_feature_flag_overrides_org_flag",
        ),
        Index("idx_org_feature_flag_overrides_org_id", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    flag_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    overridden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
