from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class OrgModelProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-task model profile for an organization.

    One row per (organization_id, task_type). When a profile exists for a
    task type the resolution service uses it instead of the env default.
    """

    __tablename__ = "org_model_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "task_type",
            name="uq_org_model_profiles_org_task",
        ),
        Index("idx_org_model_profiles_org_id", "organization_id"),
        Index(
            "idx_org_model_profiles_org_task",
            "organization_id",
            "task_type",
        ),
        CheckConstraint(
            "max_tokens IS NULL OR max_tokens >= 1",
            name="org_model_profiles_max_tokens_positive",
        ),
        CheckConstraint(
            "temperature IS NULL OR (temperature >= 0 AND temperature <= 2)",
            name="org_model_profiles_temperature_range",
        ),
        CheckConstraint(
            "context_window IS NULL OR context_window >= 1",
            name="org_model_profiles_context_window_positive",
        ),
        CheckConstraint(
            "version >= 1",
            name="org_model_profiles_version_positive",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_name: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_model: Mapped[str] = mapped_column(String(255), nullable=False)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=5, scale=3), nullable=True
    )
    json_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Key of the fallback provider to use when primary fails (e.g. "openai")
    fallback_provider_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Experimental profiles are only valid for evaluation task type when
    # feature_enable_experimental_profiles is enabled
    is_experimental: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization")
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    change_log = relationship(
        "OrgModelProfileChangeLog",
        back_populates="profile",
        cascade="save-update, merge",
        order_by="OrgModelProfileChangeLog.version_number.desc()",
    )


class OrgModelProfileChangeLog(UUIDPrimaryKeyMixin, Base):
    """Immutable snapshot of an org model profile at each version."""

    __tablename__ = "org_model_profile_change_log"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "task_type",
            "version_number",
            name="uq_org_model_profile_change_log_org_task_version",
        ),
        Index("idx_org_model_profile_change_log_org_id", "organization_id"),
        Index(
            "idx_org_model_profile_change_log_org_task",
            "organization_id",
            "task_type",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="org_model_profile_change_log_version_positive",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_model_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("org_model_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    changed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    profile = relationship("OrgModelProfile", back_populates="change_log")
    changed_by = relationship("User", foreign_keys=[changed_by_id])
