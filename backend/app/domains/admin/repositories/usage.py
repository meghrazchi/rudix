from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import AuditLog, UsageEvent


class UsageRepository:
    async def create_usage_event(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        event_type: str,
        model_name: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: Decimal | None = None,
        metadata: dict | None = None,
    ) -> UsageEvent:
        usage_event = UsageEvent(
            organization_id=organization_id,
            user_id=user_id,
            event_type=event_type,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            metadata_json=metadata or {},
        )
        session.add(usage_event)
        await session.flush()
        await session.refresh(usage_event)
        return usage_event

    async def create_audit_log(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        audit_log = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata or {},
        )
        session.add(audit_log)
        await session.flush()
        await session.refresh(audit_log)
        return audit_log

    async def list_usage_events(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        user_id: UUID | None = None,
    ) -> list[UsageEvent]:
        statement = select(UsageEvent).where(UsageEvent.organization_id == organization_id)
        if from_created_at is not None:
            statement = statement.where(UsageEvent.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(UsageEvent.created_at <= to_created_at)
        if user_id is not None:
            statement = statement.where(UsageEvent.user_id == user_id)

        result = await session.execute(statement.order_by(UsageEvent.created_at.asc(), UsageEvent.id.asc()))
        return list(result.scalars().all())

    async def list_audit_logs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        user_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> list[AuditLog]:
        statement = select(AuditLog).where(AuditLog.organization_id == organization_id)
        if from_created_at is not None:
            statement = statement.where(AuditLog.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(AuditLog.created_at <= to_created_at)
        if user_id is not None:
            statement = statement.where(AuditLog.user_id == user_id)
        if action is not None:
            statement = statement.where(AuditLog.action == action)
        if resource_type is not None:
            statement = statement.where(AuditLog.resource_type == resource_type)

        statement = (
            statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(statement)
        return list(result.scalars().all())

    async def count_audit_logs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        user_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> int:
        statement = select(func.count(AuditLog.id)).where(AuditLog.organization_id == organization_id)
        if from_created_at is not None:
            statement = statement.where(AuditLog.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(AuditLog.created_at <= to_created_at)
        if user_id is not None:
            statement = statement.where(AuditLog.user_id == user_id)
        if action is not None:
            statement = statement.where(AuditLog.action == action)
        if resource_type is not None:
            statement = statement.where(AuditLog.resource_type == resource_type)

        result = await session.execute(statement)
        return int(result.scalar_one())

    async def count_audit_logs_grouped_by_action(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        action_prefix: str | None = None,
    ) -> dict[str, int]:
        statement = (
            select(AuditLog.action, func.count(AuditLog.id))
            .where(AuditLog.organization_id == organization_id)
            .group_by(AuditLog.action)
        )
        if from_created_at is not None:
            statement = statement.where(AuditLog.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(AuditLog.created_at <= to_created_at)
        if action_prefix:
            statement = statement.where(AuditLog.action.like(f"{action_prefix}%"))

        rows = (await session.execute(statement)).all()
        return {str(action): int(count) for action, count in rows}
