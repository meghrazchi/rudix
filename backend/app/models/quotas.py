from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class OrgQuotaPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Org-level quota limits. One row per organization."""

    __tablename__ = "org_quota_policy"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_org_quota_policy_org"),
        Index("idx_org_quota_policy_org_id", "organization_id"),
        CheckConstraint("version >= 1", name="org_quota_policy_version_positive"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # {"uploads": {"soft_limit": 100, "hard_limit": 200, "reset_window": "per_day"}, ...}
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization")
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    change_log = relationship(
        "OrgQuotaChangeLog",
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="OrgQuotaChangeLog.version_number.desc()",
    )


class OrgQuotaUsage(UUIDPrimaryKeyMixin, Base):
    """Current usage counter per org per quota type. Reset when next_reset_at passes."""

    __tablename__ = "org_quota_usage"
    __table_args__ = (
        UniqueConstraint("organization_id", "quota_type", name="uq_org_quota_usage_org_type"),
        Index("idx_org_quota_usage_org_id", "organization_id"),
        Index("idx_org_quota_usage_org_type", "organization_id", "quota_type"),
        CheckConstraint(
            "current_value >= 0",
            name="org_quota_usage_current_value_non_negative",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    quota_type: Mapped[str] = mapped_column(String(64), nullable=False)
    current_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # None when reset_window is "none" (permanent cap)
    next_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization")


class OrgQuotaOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Manual hard-limit override for a specific user or org-wide."""

    __tablename__ = "org_quota_override"
    __table_args__ = (
        Index("idx_org_quota_override_org_id", "organization_id"),
        Index("idx_org_quota_override_org_type", "organization_id", "quota_type"),
        CheckConstraint(
            "hard_limit_override IS NULL OR hard_limit_override >= 0",
            name="org_quota_override_hard_limit_non_negative",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    quota_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # None = org-wide override; set = applies only to that user
    target_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    # None = remove hard limit (unlimited)
    hard_limit_override: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization")
    target_user = relationship("User", foreign_keys=[target_user_id])
    created_by = relationship("User", foreign_keys=[created_by_id])


class OrgQuotaChangeLog(UUIDPrimaryKeyMixin, Base):
    """Immutable snapshot of org quota policy at each version."""

    __tablename__ = "org_quota_change_log"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "version_number",
            name="uq_org_quota_change_log_org_version",
        ),
        Index("idx_org_quota_change_log_org_id", "organization_id"),
        Index(
            "idx_org_quota_change_log_org_version",
            "organization_id",
            "version_number",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="org_quota_change_log_version_positive",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_quota_policy_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("org_quota_policy.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    changed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    policy = relationship("OrgQuotaPolicy", back_populates="change_log")
    changed_by = relationship("User", foreign_keys=[changed_by_id])
