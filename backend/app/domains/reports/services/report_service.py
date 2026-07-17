from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from math import ceil
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reports.schemas.reports import (
    ReportActionItem,
    ReportChartPoint,
    ReportEventAccepted,
    ReportEventCreate,
    ReportMetric,
    ReportPage,
    ReportResponse,
    ReportTableRow,
)
from app.models.report import ReportEvent

_SORT_COLUMNS = {
    "occurred_at": ReportEvent.occurred_at,
    "category": ReportEvent.category,
    "event_type": ReportEvent.event_type,
    "status": ReportEvent.status,
    "count": ReportEvent.count,
    "value": ReportEvent.value,
}
_FAILURE_STATUSES = ("failed", "error", "denied", "rejected")


class ReportService:
    async def record_event(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        event: ReportEventCreate,
    ) -> ReportEventAccepted:
        if event.idempotency_key:
            existing = await session.scalar(
                select(ReportEvent.id).where(
                    ReportEvent.organization_id == organization_id,
                    ReportEvent.idempotency_key == event.idempotency_key,
                )
            )
            if existing is not None:
                return ReportEventAccepted(id=existing, deduplicated=True)
        row = ReportEvent(organization_id=organization_id, user_id=user_id, **event.model_dump())
        session.add(row)
        await session.flush()
        return ReportEventAccepted(id=row.id)

    @staticmethod
    def _filtered(
        *,
        organization_id: UUID,
        from_at: datetime,
        to_at: datetime,
        category: str | None,
        workspace_id: UUID | None,
        collection_id: UUID | None,
        connector_id: UUID | None,
        user_id: UUID | None,
        team_id: UUID | None,
        source_id: UUID | None,
    ) -> Select[tuple[ReportEvent]]:
        stmt = select(ReportEvent).where(
            ReportEvent.organization_id == organization_id,
            ReportEvent.occurred_at >= from_at,
            ReportEvent.occurred_at <= to_at,
        )
        for column, value in (
            (ReportEvent.category, category),
            (ReportEvent.workspace_id, workspace_id),
            (ReportEvent.collection_id, collection_id),
            (ReportEvent.connector_id, connector_id),
            (ReportEvent.user_id, user_id),
            (ReportEvent.team_id, team_id),
            (ReportEvent.source_id, source_id),
        ):
            if value is not None:
                stmt = stmt.where(column == value)
        return stmt

    async def build_report(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_at: datetime,
        to_at: datetime,
        category: str | None = None,
        workspace_id: UUID | None = None,
        collection_id: UUID | None = None,
        connector_id: UUID | None = None,
        user_id: UUID | None = None,
        team_id: UUID | None = None,
        source_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
        sort: str = "occurred_at",
        direction: str = "desc",
    ) -> ReportResponse:
        base = self._filtered(
            organization_id=organization_id,
            from_at=from_at,
            to_at=to_at,
            category=category,
            workspace_id=workspace_id,
            collection_id=collection_id,
            connector_id=connector_id,
            user_id=user_id,
            team_id=team_id,
            source_id=source_id,
        )
        total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
        count_events = base.subquery()
        total_count = int(
            await session.scalar(select(func.coalesce(func.sum(count_events.c.count), 0))) or 0
        )
        category_rows = (
            await session.execute(
                base.with_only_columns(ReportEvent.category, func.sum(ReportEvent.count))
                .group_by(ReportEvent.category)
                .order_by(ReportEvent.category)
            )
        ).all()
        filtered_events = base.subquery()
        failure_count = int(
            await session.scalar(
                select(func.coalesce(func.sum(filtered_events.c.count), 0)).where(
                    filtered_events.c.status.in_(_FAILURE_STATUSES)
                )
            )
            or 0
        )
        # Aggregate by database date bucket; bounded output is independent of table page size.
        day = func.date(ReportEvent.occurred_at)
        chart_rows = (
            await session.execute(
                base.with_only_columns(day, ReportEvent.category, func.sum(ReportEvent.count))
                .group_by(day, ReportEvent.category)
                .order_by(day, ReportEvent.category)
            )
        ).all()
        column = _SORT_COLUMNS[sort]
        order = column.asc() if direction == "asc" else column.desc()
        rows = (
            (
                await session.execute(
                    base.order_by(order, ReportEvent.id.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        metrics = [ReportMetric(key="events.total", value=Decimal(total_count))]
        metrics.extend(
            ReportMetric(key=f"events.{name}", value=Decimal(value or 0))
            for name, value in category_rows
        )
        actions = []
        if failure_count:
            actions.append(
                ReportActionItem(
                    key="events.failures",
                    severity="warning",
                    count=failure_count,
                    title="Review failed, denied, or rejected report events",
                )
            )
        return ReportResponse(
            organization_id=organization_id,
            generated_at=datetime.now(tz=UTC),
            from_at=from_at,
            to_at=to_at,
            metrics=metrics,
            chart=[
                ReportChartPoint(bucket=str(bucket), series=name, value=Decimal(value or 0))
                for bucket, name, value in chart_rows
            ],
            table=[ReportTableRow.model_validate(row, from_attributes=True) for row in rows],
            action_items=actions,
            pagination=ReportPage(
                page=page,
                page_size=page_size,
                total=total,
                pages=ceil(total / page_size) if total else 0,
            ),
        )
