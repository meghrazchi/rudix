"""Due-job polling for the ``connectors.sync.schedule_poll`` beat task (R06-11).

One statement selects the due jobs: active, ``next_run_at`` NULL or past, and no queued or
running run (``NOT EXISTS``), ordered ``next_run_at NULLS FIRST``, limited to
``CONNECTOR_SYNC_POLL_BATCH_SIZE`` and locked ``FOR UPDATE SKIP LOCKED`` on PostgreSQL so
two pollers never claim the same job. The same statement returns the active-run counts
per organization and connection when a concurrency cap is set.

``next_run_at`` bookkeeping:

- NULL (jobs created before 0.6.0, or never scheduled): the 0.5 rule
  (``last_run_at + interval``) decides once; a job that is not due gets that time stored.
- After a queued run is created: ``now + interval`` (interval clamped to 5..10080 min).
- ``manual_only`` schedules get ``MANUAL_ONLY_NEXT_RUN_AT`` (far future), so they never
  match the due query again; manual triggers do not read ``next_run_at``.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_connector_sync_deferred
from app.domains.connectors.services.sync.common import next_run_due, schedule_interval_minutes
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import ConnectorSyncJobStatus, ConnectorSyncRunStatus

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine

MANUAL_ONLY_NEXT_RUN_AT = datetime(9999, 1, 1, tzinfo=UTC)
_ACTIVE = (ConnectorSyncRunStatus.queued.value, ConnectorSyncRunStatus.running.value)
_logger = get_logger("connectors.sync_engine")


def _active_count(column: Any, value: Any) -> Any:
    return (
        select(func.count(ConnectorSyncRun.id))
        .where(column == value, ConnectorSyncRun.status.in_(_ACTIVE))
        .correlate(ConnectorSyncJob)
        .scalar_subquery()
    )


def due_jobs_statement(now: datetime, *, limit: int, postgres: bool) -> Any:
    org_cap = settings.connector_sync_max_concurrent_per_org
    connection_cap = settings.connector_sync_max_concurrent_per_connection
    columns: list[Any] = [ConnectorSyncJob]
    if org_cap > 0:
        columns.append(
            _active_count(ConnectorSyncRun.organization_id, ConnectorSyncJob.organization_id)
        )
    if connection_cap > 0:
        columns.append(
            _active_count(ConnectorSyncRun.connection_id, ConnectorSyncJob.connection_id)
        )
    no_active_run = ~exists().where(
        ConnectorSyncRun.sync_job_id == ConnectorSyncJob.id,
        ConnectorSyncRun.status.in_(_ACTIVE),
    )
    stmt = (
        select(*columns)
        .where(
            ConnectorSyncJob.status == ConnectorSyncJobStatus.active.value,
            or_(ConnectorSyncJob.next_run_at.is_(None), ConnectorSyncJob.next_run_at <= now),
            no_active_run,
        )
        .order_by(ConnectorSyncJob.next_run_at.asc().nulls_first(), ConnectorSyncJob.id)
        .limit(limit)
    )
    if postgres:
        stmt = stmt.with_for_update(skip_locked=True, of=ConnectorSyncJob)
    return stmt


def _not_due_until(job: ConnectorSyncJob, interval_minutes: int) -> datetime:
    """When an interval job with NULL ``next_run_at`` that is not due yet becomes due.

    Only called when ``next_run_due`` is false, so ``last_run_at`` is set.
    """
    last_run = job.last_run_at or datetime.now(UTC)
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=UTC)
    return last_run + timedelta(minutes=interval_minutes)


class SyncScheduler:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    async def dispatch_due_syncs(self, session: AsyncSession) -> list[tuple[UUID, UUID]]:
        """Claim due jobs, create their queued runs, and return (sync_run_id, org_id) pairs.

        Does NOT enqueue Celery tasks; callers do that after commit.
        """
        now = datetime.now(UTC)
        postgres = session.get_bind().dialect.name == "postgresql"
        stmt = due_jobs_statement(
            now, limit=settings.connector_sync_poll_batch_size, postgres=postgres
        )
        rows = list((await session.execute(stmt)).all())
        org_cap = settings.connector_sync_max_concurrent_per_org
        connection_cap = settings.connector_sync_max_concurrent_per_connection
        claimed_org: Counter[UUID] = Counter()
        claimed_connection: Counter[UUID] = Counter()
        runs: list[ConnectorSyncRun] = []
        for row in rows:
            job: ConnectorSyncJob = row[0]
            extra = list(row[1:])
            org_active = int(extra.pop(0)) if org_cap > 0 else 0
            connection_active = int(extra.pop(0)) if connection_cap > 0 else 0
            interval = schedule_interval_minutes(job)
            if interval is None:
                job.next_run_at = MANUAL_ONLY_NEXT_RUN_AT
                continue
            if job.next_run_at is None and not next_run_due(job, now):
                job.next_run_at = _not_due_until(job, interval)
                continue
            if org_cap > 0 and org_active + claimed_org[job.organization_id] >= org_cap:
                record_connector_sync_deferred("org_cap")
                continue
            connection_claims = claimed_connection[job.connection_id]
            if connection_cap > 0 and connection_active + connection_claims >= connection_cap:
                record_connector_sync_deferred("connection_cap")
                continue
            claimed_org[job.organization_id] += 1
            claimed_connection[job.connection_id] += 1
            runs.append(self._queued_run(job, now))
            job.next_run_at = now + timedelta(minutes=interval)
        session.add_all(runs)
        await session.flush()
        if runs:
            _logger.info("connector.sync.due_jobs_claimed", jobs=len(rows), runs=len(runs))
        return [(run.id, run.organization_id) for run in runs]

    @staticmethod
    def _queued_run(job: ConnectorSyncJob, now: datetime) -> ConnectorSyncRun:
        """A queued run built in memory, so the poll issues no per-job SELECT."""
        return ConnectorSyncRun(
            id=uuid4(),
            organization_id=job.organization_id,
            sync_job_id=job.id,
            connection_id=job.connection_id,
            external_source_id=job.external_source_id,
            status=ConnectorSyncRunStatus.queued.value,
            sync_version=int(now.timestamp()),
            cursor_before_json=dict(job.cursor_json or {}),
            trigger_type="scheduled",
        )
