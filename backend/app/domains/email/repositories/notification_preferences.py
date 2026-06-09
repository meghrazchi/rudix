"""Repository for UserNotificationPreference records."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import UserNotificationPreference
from app.models.enums import EmailEventType


class NotificationPreferencesRepository:
    async def is_email_enabled(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        event_type: EmailEventType,
    ) -> bool:
        """Return True if the user has not opted out of this event type. Default: enabled."""
        result = await session.execute(
            select(UserNotificationPreference).where(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.organization_id == organization_id,
                UserNotificationPreference.event_type == event_type.value,
            )
        )
        pref = result.scalar_one_or_none()
        return pref.email_enabled if pref is not None else True

    async def get_preferences(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> list[UserNotificationPreference]:
        result = await session.execute(
            select(UserNotificationPreference).where(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.organization_id == organization_id,
            )
        )
        return list(result.scalars().all())

    async def upsert_preference(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        event_type: EmailEventType,
        email_enabled: bool,
    ) -> UserNotificationPreference:
        result = await session.execute(
            select(UserNotificationPreference).where(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.organization_id == organization_id,
                UserNotificationPreference.event_type == event_type.value,
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = UserNotificationPreference(
                id=uuid4(),
                organization_id=organization_id,
                user_id=user_id,
                event_type=event_type.value,
                email_enabled=email_enabled,
            )
            session.add(pref)
        else:
            pref.email_enabled = email_enabled
        await session.flush()
        return pref
