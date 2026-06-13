from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class UsageEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="usage_events_input_tokens_non_negative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="usage_events_output_tokens_non_negative",
        ),
        CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name="usage_events_cost_non_negative"),
        CheckConstraint(
            "retry_count IS NULL OR retry_count >= 0",
            name="usage_events_retry_count_non_negative",
        ),
        Index("idx_usage_org_created", "organization_id", "created_at"),
        Index("idx_usage_org_provider_created", "organization_id", "provider_key", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    # Provider observability fields (F228)
    provider_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    organization = relationship("Organization", back_populates="usage_events")
    user = relationship("User", back_populates="usage_events")


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("idx_audit_logs_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    organization = relationship("Organization", back_populates="audit_logs")
    user = relationship("User", back_populates="audit_logs")
