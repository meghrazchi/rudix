"""Persistence for the retention purge (R04-09).

Deletes go through a fixed allow-list of tables so a table name never comes from input.
Each batch is ``DELETE FROM t WHERE id IN (SELECT id FROM t WHERE organization_id = :org AND
created_at < :cutoff ORDER BY created_at LIMIT :batch)``, which walks the
``(organization_id, created_at)`` index of each table.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import CursorResult, Table, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_timeline import ActivityTimelineEvent
from app.models.authorization import AuthorizationDecisionLog
from app.models.governance import OrganizationGovernancePolicy
from app.models.organization import Organization
from app.models.usage import AuditLog, UsageEvent
from app.models.webhook import WebhookDelivery

RETENTION_TABLES: dict[str, Table] = {
    "usage_events": cast(Table, UsageEvent.__table__),
    "audit_logs": cast(Table, AuditLog.__table__),
    "authorization_decision_logs": cast(Table, AuthorizationDecisionLog.__table__),
    "activity_timeline_events": cast(Table, ActivityTimelineEvent.__table__),
    "webhook_deliveries": cast(Table, WebhookDelivery.__table__),
}


class RetentionRepository:
    async def list_organization_ids(self, session: AsyncSession) -> list[UUID]:
        result = await session.execute(select(Organization.id).order_by(Organization.id))
        return list(result.scalars().all())

    async def audit_retention_overrides(self, session: AsyncSession) -> dict[UUID, int]:
        """Organisation ID -> audit retention override, for organisations that set one."""
        result = await session.execute(
            select(
                OrganizationGovernancePolicy.organization_id,
                OrganizationGovernancePolicy.audit_log_retention_days,
            ).where(OrganizationGovernancePolicy.audit_log_retention_days.is_not(None))
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def delete_batch(
        self,
        session: AsyncSession,
        *,
        table_name: str,
        organization_id: UUID,
        cutoff: datetime,
        batch_size: int,
    ) -> int:
        """Delete up to ``batch_size`` of the oldest rows older than ``cutoff``; return count."""
        table = RETENTION_TABLES[table_name]
        oldest = (
            select(table.c.id)
            .where(table.c.organization_id == organization_id, table.c.created_at < cutoff)
            .order_by(table.c.created_at)
            .limit(batch_size)
        )
        statement = delete(table).where(table.c.id.in_(oldest))
        result = cast(CursorResult[object], await session.execute(statement))
        return int(result.rowcount or 0)
