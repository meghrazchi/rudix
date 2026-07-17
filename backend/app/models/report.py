from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class ReportEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-free, tenant-scoped fact used by reporting aggregations."""

    __tablename__ = "report_events"
    __table_args__ = (
        CheckConstraint("count >= 0", name="report_events_count_non_negative"),
        CheckConstraint("value IS NULL OR value >= 0", name="report_events_value_non_negative"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="report_events_duration_non_negative"
        ),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_report_events_org_idempotency"
        ),
        Index("idx_report_events_org_occurred", "organization_id", "occurred_at"),
        Index(
            "idx_report_events_org_category_occurred", "organization_id", "category", "occurred_at"
        ),
        Index("idx_report_events_org_user_occurred", "organization_id", "user_id", "occurred_at"),
        Index(
            "idx_report_events_org_collection_occurred",
            "organization_id",
            "collection_id",
            "occurred_at",
        ),
        Index(
            "idx_report_events_org_connector_occurred",
            "organization_id",
            "connector_id",
            "occurred_at",
        ),
        Index(
            "idx_report_events_org_source_occurred", "organization_id", "source_id", "occurred_at"
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("collections.id", ondelete="SET NULL"), nullable=True
    )
    connector_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    team_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("external_sources.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
