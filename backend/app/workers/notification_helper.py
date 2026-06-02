"""Thin sync wrapper for emitting notifications from Celery worker tasks."""

from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger

_logger = get_logger("worker.notifications")


def _parse_optional_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def _emit_notification_async(
    *,
    organization_id: UUID,
    user_id: UUID,
    event_type: str,
    severity: str,
    title: str,
    message: str | None,
    href: str | None,
    source_id: str | None,
) -> None:
    from app.db.session import SessionLocal
    from app.domains.notifications.repositories.notifications import NotificationRepository
    from app.models.enums import NotificationEventType, NotificationSeverity

    repo = NotificationRepository()
    async with SessionLocal() as session:
        await repo.create_notification(
            session,
            organization_id=organization_id,
            user_id=user_id,
            event_type=NotificationEventType(event_type),
            severity=NotificationSeverity(severity),
            title=title,
            message=message,
            href=href,
            source_id=source_id,
        )
        await session.commit()


def emit_notification(
    *,
    organization_id: str | None,
    user_id: str | None,
    event_type: str,
    severity: str,
    title: str,
    message: str | None = None,
    href: str | None = None,
    source_id: str | None = None,
) -> None:
    """Emit a user notification from a Celery worker task. Silently swallows errors."""
    org_uuid = _parse_optional_uuid(organization_id)
    user_uuid = _parse_optional_uuid(user_id)
    if org_uuid is None or user_uuid is None:
        return

    from app.workers.async_runtime import run_async

    try:
        run_async(
            _emit_notification_async(
                organization_id=org_uuid,
                user_id=user_uuid,
                event_type=event_type,
                severity=severity,
                title=title,
                message=message,
                href=href,
                source_id=source_id,
            )
        )
    except Exception:
        _logger.warning("notification.emit.failed", event_type=event_type, source_id=source_id)
