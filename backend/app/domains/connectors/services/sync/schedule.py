"""Due-job polling for the ``connectors.sync.schedule_poll`` beat task (R06-11)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.connectors.services.sync.common import next_run_due
from app.models.connector_sync import ConnectorSyncJob
from app.models.enums import ConnectorSyncJobStatus

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine


class SyncScheduler:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    async def dispatch_due_syncs(self, session: AsyncSession) -> list[tuple[UUID, UUID]]:
        """Find all active sync jobs due for a run; create queued runs and return their IDs.

        Returns list of (sync_run_id, organization_id) pairs for dispatch.
        Does NOT enqueue Celery tasks — callers do that to keep this method testable.
        """
        now = datetime.now(UTC)
        result = await session.execute(
            select(ConnectorSyncJob).where(
                ConnectorSyncJob.status == ConnectorSyncJobStatus.active.value,
            )
        )
        jobs = list(result.scalars().all())
        dispatched: list[tuple[UUID, UUID]] = []
        planner = self.engine.planner
        for job in jobs:
            if not next_run_due(job, now):
                continue
            if await planner.has_active_run(session, job_id=job.id):
                continue
            run = await planner.create_queued_run(session, job=job, trigger_type="scheduled")
            dispatched.append((run.id, job.organization_id))
        if dispatched:
            await session.flush()
        return dispatched
