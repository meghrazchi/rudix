from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    notification_id: str
    event_type: str
    severity: str
    title: str
    message: str | None = None
    href: str | None = None
    source_id: str | None = None
    is_read: bool
    created_at: datetime

    @classmethod
    def from_model(cls, n: object) -> "NotificationResponse":
        from app.models.notification import Notification

        assert isinstance(n, Notification)
        return cls(
            notification_id=str(n.id),
            event_type=n.event_type,
            severity=n.severity,
            title=n.title,
            message=n.message,
            href=n.href,
            source_id=n.source_id,
            is_read=n.is_read,
            created_at=n.created_at,
        )


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    limit: int
    offset: int
    unread_count: int


class MarkReadResponse(BaseModel):
    notification_id: str
    is_read: bool


class MarkAllReadResponse(BaseModel):
    marked_count: int


class UnreadCountResponse(BaseModel):
    unread_count: int
