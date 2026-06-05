from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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


class OrgModelProviderSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Org-level model provider and fallback policy. One row per organization."""

    __tablename__ = "org_model_provider_settings"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_org_model_provider_settings_org"),
        Index("idx_org_model_provider_settings_org_id", "organization_id"),
        CheckConstraint(
            "max_tokens IS NULL OR max_tokens >= 1",
            name="org_model_provider_settings_max_tokens_positive",
        ),
        CheckConstraint(
            "timeout_seconds IS NULL OR timeout_seconds >= 1",
            name="org_model_provider_settings_timeout_positive",
        ),
        CheckConstraint(
            "max_retries IS NULL OR (max_retries >= 0 AND max_retries <= 10)",
            name="org_model_provider_settings_max_retries_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="org_model_provider_settings_version_positive",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # JSON array of model name strings that are explicitly disabled for this org
    disabled_models: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Monotonically increasing; bumped on every update
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization")
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    change_log = relationship(
        "OrgModelProviderChangeLog",
        back_populates="settings",
        cascade="all, delete-orphan",
        order_by="OrgModelProviderChangeLog.version_number.desc()",
    )


class OrgModelProviderChangeLog(UUIDPrimaryKeyMixin, Base):
    """Immutable snapshot of org model provider settings at each version."""

    __tablename__ = "org_model_provider_change_log"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "version_number",
            name="uq_org_model_provider_change_log_org_version",
        ),
        Index("idx_org_model_provider_change_log_org_id", "organization_id"),
        Index(
            "idx_org_model_provider_change_log_org_version",
            "organization_id",
            "version_number",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="org_model_provider_change_log_version_positive",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Back-reference to the owning settings row (nullable so log survives if settings are reset)
    org_model_provider_settings_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("org_model_provider_settings.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    settings_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    changed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    settings = relationship("OrgModelProviderSettings", back_populates="change_log")
    changed_by = relationship("User", foreign_keys=[changed_by_id])
