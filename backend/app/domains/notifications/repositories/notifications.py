from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationEventType, NotificationSeverity
from app.models.notification import Notification

_MAX_NOTIFICATIONS_PER_USER = 200


class NotificationRepository:
    async def create_notification(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        event_type: NotificationEventType,
        severity: NotificationSeverity,
        title: str,
        message: str | None = None,
        href: str | None = None,
        source_id: str | None = None,
    ) -> Notification:
        notification = Notification(
            organization_id=organization_id,
            user_id=user_id,
            event_type=event_type.value,
            severity=severity.value,
            title=title,
            message=message,
            href=href,
            source_id=source_id,
            is_read=False,
        )
        session.add(notification)
        await session.flush()
        await session.refresh(notification)
        return notification

    async def list_notifications(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Notification]:
        result = await session.execute(
            select(Notification)
            .where(
                Notification.organization_id == organization_id,
                Notification.user_id == user_id,
            )
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_with_counts(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Notification], int, int]:
        items = await self.list_notifications(
            session, organization_id=organization_id, user_id=user_id, limit=limit, offset=offset
        )
        total = await self.count_notifications(
            session, organization_id=organization_id, user_id=user_id
        )
        unread = await self.count_unread(session, organization_id=organization_id, user_id=user_id)
        return items, total, unread

    async def count_notifications(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(Notification.id)).where(
                Notification.organization_id == organization_id,
                Notification.user_id == user_id,
            )
        )
        return result.scalar_one()

    async def count_unread(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(Notification.id)).where(
                Notification.organization_id == organization_id,
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
        )
        return result.scalar_one()

    async def get_notification(
        self,
        session: AsyncSession,
        *,
        notification_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> Notification | None:
        result = await session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.organization_id == organization_id,
                Notification.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_read(
        self,
        session: AsyncSession,
        *,
        notification_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        is_read: bool,
    ) -> bool:
        result = await session.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.organization_id == organization_id,
                Notification.user_id == user_id,
            )
            .values(is_read=is_read)
            .returning(Notification.id)
        )
        await session.flush()
        return result.scalar_one_or_none() is not None

    async def mark_all_read(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> int:
        result = await session.execute(
            update(Notification)
            .where(
                Notification.organization_id == organization_id,
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
            .values(is_read=True)
            .returning(Notification.id)
        )
        await session.flush()
        return len(result.all())
