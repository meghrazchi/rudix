from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

WEBHOOK_EVENT_TYPES = frozenset(
    {
        "document.indexed",
        "document.failed",
        "document.deleted",
        "evaluation.completed",
        "evaluation.failed",
        "feedback.created",
        "connector.sync_failed",
        "quota.reached",
    }
)


class Webhook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhooks"
    __table_args__ = (Index("idx_webhooks_org_id", "organization_id"),)

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # First 16 chars of raw secret — safe to show in UI
    secret_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    # SHA-256 hex digest of the signing secret — only value stored long-term
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # e.g. {"max_attempts": 5, "backoff_seconds": 60}
    retry_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization = relationship("Organization")
    created_by = relationship("User", foreign_keys=[created_by_id])
    deliveries = relationship(
        "WebhookDelivery",
        back_populates="webhook",
        cascade="all, delete-orphan",
    )


class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("idx_webhook_deliveries_webhook_id", "webhook_id"),
        Index("idx_webhook_deliveries_org_id", "organization_id"),
    )

    webhook_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # pending / delivered / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    webhook = relationship("Webhook", back_populates="deliveries")
