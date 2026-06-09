from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EmailDeliveryStatus, EmailEventType

_EVENT_TYPES = ", ".join(f"'{v}'" for v in EmailEventType)
_DELIVERY_STATUSES = ", ".join(f"'{v}'" for v in EmailDeliveryStatus)


class EmailDeliveryLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_delivery_logs"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({_EVENT_TYPES})",
            name="email_delivery_logs_event_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({_DELIVERY_STATUSES})",
            name="email_delivery_logs_status_allowed",
        ),
        Index("idx_email_delivery_org_created", "organization_id", "created_at"),
        Index("idx_email_delivery_user_event", "user_id", "event_type"),
        Index("idx_email_delivery_status", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EmailDeliveryStatus.queued.value
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text(), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)

    organization = relationship("Organization")
    user = relationship("User")


class UserNotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user opt-in/out for each transactional email event type."""

    __tablename__ = "user_notification_preferences"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({_EVENT_TYPES})",
            name="user_notif_pref_event_type_allowed",
        ),
        Index(
            "idx_user_notif_pref_user_org_event",
            "user_id",
            "organization_id",
            "event_type",
            unique=True,
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    email_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)

    organization = relationship("Organization")
    user = relationship("User")
