"""Repository for EmailDeliveryLog records."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import EmailDeliveryLog
from app.models.enums import EmailDeliveryStatus, EmailEventType


class EmailDeliveryRepository:
    async def create_log(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        event_type: EmailEventType,
        recipient_email: str,
        subject: str,
        provider: str,
    ) -> UUID:
        log = EmailDeliveryLog(
            id=uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            event_type=event_type.value,
            recipient_email=recipient_email,
            subject=subject,
            provider=provider,
            status=EmailDeliveryStatus.queued.value,
            attempt_count=1,
        )
        session.add(log)
        await session.flush()
        return log.id

    async def update_status(
        self,
        session: AsyncSession,
        *,
        log_id: UUID,
        status: EmailDeliveryStatus,
        provider_message_id: str | None,
        error_detail: str | None,
    ) -> None:
        await session.execute(
            update(EmailDeliveryLog)
            .where(EmailDeliveryLog.id == log_id)
            .values(
                status=status.value,
                provider_message_id=provider_message_id,
                error_detail=error_detail,
                updated_at=datetime.now(UTC),
            )
        )

    async def increment_attempt(
        self,
        session: AsyncSession,
        *,
        log_id: UUID,
    ) -> None:
        from sqlalchemy import text

        await session.execute(
            update(EmailDeliveryLog)
            .where(EmailDeliveryLog.id == log_id)
            .values(
                attempt_count=EmailDeliveryLog.attempt_count + 1,
                updated_at=datetime.now(UTC),
            )
        )

    async def list_logs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EmailDeliveryLog]:
        result = await session.execute(
            select(EmailDeliveryLog)
            .where(EmailDeliveryLog.organization_id == organization_id)
            .order_by(EmailDeliveryLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_logs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(EmailDeliveryLog.id)).where(
                EmailDeliveryLog.organization_id == organization_id
            )
        )
        return result.scalar_one()
