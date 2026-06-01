from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import NotificationEventType, NotificationSeverity

_EVENT_TYPES = ", ".join(f"'{v}'" for v in NotificationEventType)
_SEVERITIES = ", ".join(f"'{v}'" for v in NotificationSeverity)


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({_EVENT_TYPES})",
            name="notifications_event_type_allowed",
        ),
        CheckConstraint(
            f"severity IN ({_SEVERITIES})",
            name="notifications_severity_allowed",
        ),
        Index("idx_notifications_user_org", "user_id", "organization_id", "created_at"),
        Index("idx_notifications_unread", "user_id", "organization_id", "is_read"),
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
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=NotificationSeverity.info.value)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    href: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")

    organization = relationship("Organization")
    user = relationship("User")
