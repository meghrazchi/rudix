"""Sync planning: job CRUD, manual/full/retry triggers, queued runs (R06-11 split)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.services.sync.common import SyncEngineError
from app.models.connector import ConnectorConnection
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import (
    ConnectorConnectionStatus,
    ConnectorSyncJobStatus,
    ConnectorSyncRunStatus,
)

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine

ACTIVE_RUN_STATUSES = (ConnectorSyncRunStatus.queued.value, ConnectorSyncRunStatus.running.value)


class SyncPlanner:
    """Creates and reads jobs and runs. Reads engine collaborators at call time."""

    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    # -- jobs ---------------------------------------------------------------

    async def create_sync_job(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        name: str,
        user_id: UUID | None = None,
        external_source_id: UUID | None = None,
        collection_id: UUID | None = None,
        schedule: dict | None = None,
    ) -> ConnectorSyncJob:
        engine = self.engine
        connection = await engine.repository.get_connection(
            session, organization_id=organization_id, connection_id=connection_id
        )
        if connection is None:
            raise SyncEngineError("connector connection not found")
        job = await engine.repository.create_sync_job(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            name=name,
            external_source_id=external_source_id,
            collection_id=collection_id,
            schedule=schedule or {"type": "interval", "interval_minutes": 60},
        )
        job_metadata: dict[str, object] = {
            "connection_id": str(connection_id),
            "external_source_id": str(external_source_id) if external_source_id else None,
            "collection_id": str(collection_id) if collection_id else None,
            "job_name": name,
        }
        if external_source_id is not None:
            await engine._audit(
                session,
                organization_id=organization_id,
                user_id=user_id,
                action=ConnectorAuditAction.source_selected.value,
                resource_type="connector_sync_job",
                resource_id=job.id,
                metadata=dict(job_metadata),
            )
        await engine._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.sync_job_created.value,
            resource_type="connector_sync_job",
            resource_id=job.id,
            metadata=job_metadata,
        )
        return job

    async def update_sync_job_status(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        job_id: UUID,
        status: ConnectorSyncJobStatus,
        user_id: UUID | None = None,
    ) -> ConnectorSyncJob:
        job = await self.require_sync_job(session, organization_id, job_id)
        job.status = status.value
        await session.flush()
        await session.refresh(job)
        await self.engine._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.sync_job_status_changed.value,
            resource_type="connector_sync_job",
            resource_id=job.id,
            metadata={"connection_id": str(job.connection_id), "status": status.value},
        )
        return job

    async def get_sync_job(
        self, session: AsyncSession, *, organization_id: UUID, job_id: UUID
    ) -> ConnectorSyncJob | None:
        result = await session.execute(
            select(ConnectorSyncJob)
            .options(selectinload(ConnectorSyncJob.sync_runs))
            .where(
                ConnectorSyncJob.id == job_id,
                ConnectorSyncJob.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_sync_jobs(
        self, session: AsyncSession, *, organization_id: UUID, connection_id: UUID
    ) -> list[ConnectorSyncJob]:
        result = await session.execute(
            select(ConnectorSyncJob)
            .where(
                ConnectorSyncJob.organization_id == organization_id,
                ConnectorSyncJob.connection_id == connection_id,
            )
            .order_by(ConnectorSyncJob.created_at.desc())
        )
        return list(result.scalars().all())

    async def _default_job(
        self, session: AsyncSession, *, organization_id: UUID, connection_id: UUID
    ) -> ConnectorSyncJob:
        """The connection's oldest non-disabled job, created when there is none."""
        result = await session.execute(
            select(ConnectorSyncJob)
            .where(
                ConnectorSyncJob.organization_id == organization_id,
                ConnectorSyncJob.connection_id == connection_id,
                ConnectorSyncJob.status != ConnectorSyncJobStatus.disabled.value,
            )
            .order_by(ConnectorSyncJob.created_at.asc())
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if job is not None:
            return job
        repository = self.engine.repository
        connection = await repository.get_connection(
            session, organization_id=organization_id, connection_id=connection_id
        )
        if connection is None:
            raise SyncEngineError("connector connection not found")
        return await repository.create_sync_job(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            name=f"{connection.display_name} — default sync",
            schedule={"type": "interval", "interval_minutes": 60},
        )

    # -- triggers -----------------------------------------------------------

    async def trigger_manual_sync(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        job_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> ConnectorSyncRun:
        if job_id is not None:
            job = await self.require_sync_job(session, organization_id, job_id)
        else:
            job = await self._default_job(
                session, organization_id=organization_id, connection_id=connection_id
            )
        await self.assert_no_active_run(session, job_id=job.id)
        run = await self.create_queued_run(session, job=job, trigger_type="manual")
        await self.engine._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.sync_manual_queued.value,
            resource_type="connector_sync_run",
            resource_id=run.id,
            metadata={
                "connection_id": str(connection_id),
                "job_id": str(job.id),
                "external_source_id": str(job.external_source_id)
                if job.external_source_id
                else None,
            },
        )
        return run

    async def retry_failed_sync(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        run_id: UUID,
        user_id: UUID | None = None,
    ) -> ConnectorSyncRun:
        run = await self.require_sync_run(session, organization_id, run_id)
        if run.status != ConnectorSyncRunStatus.failed.value:
            raise SyncEngineError(f"sync run {run_id} is not in failed state")

        job = await self.require_sync_job(session, organization_id, run.sync_job_id)
        connection = await self.engine.repository.get_connection(
            session, organization_id=organization_id, connection_id=run.connection_id
        )
        if connection is None:
            raise SyncEngineError("connector connection not found")
        if connection.status != ConnectorConnectionStatus.active.value:
            raise SyncEngineError(f"connection is not active (status={connection.status})")
        if job.status == ConnectorSyncJobStatus.disabled.value:
            raise SyncEngineError("sync job is disabled")

        await self.assert_no_active_run(session, job_id=job.id)
        retry_run = await self.engine.repository.create_sync_run(
            session,
            organization_id=organization_id,
            sync_job_id=job.id,
            connection_id=connection.id,
            sync_version=int(datetime.now(UTC).timestamp()),
            external_source_id=job.external_source_id,
            status=ConnectorSyncRunStatus.queued.value,
            cursor_before=dict(run.cursor_before_json or {}),
        )
        retry_run.trigger_type = "manual"
        await session.flush()
        await self.engine._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.sync_manual_queued.value,
            resource_type="connector_sync_run",
            resource_id=retry_run.id,
            metadata={
                "connection_id": str(connection.id),
                "job_id": str(job.id),
                "external_source_id": str(job.external_source_id)
                if job.external_source_id
                else None,
                "retry_of_run_id": str(run.id),
                "trigger_type": "retry",
            },
        )
        return retry_run

    async def trigger_full_resync(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        job_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> ConnectorSyncRun:
        """Clear the sync cursor and queue a full re-index from the provider.

        Safe to call at any time; blocks if a run is already active.
        """
        if job_id is not None:
            job = await self.require_sync_job(session, organization_id, job_id)
        else:
            job = await self._default_job(
                session, organization_id=organization_id, connection_id=connection_id
            )
        await self.assert_no_active_run(session, job_id=job.id)
        # Wipe the cursor so the next run is a full sync regardless of prior state.
        job.cursor_json = {}
        await session.flush()

        run = await self.create_queued_run(session, job=job, trigger_type="manual")
        await self.engine._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.sync_full_resync_triggered.value,
            resource_type="connector_sync_run",
            resource_id=run.id,
            metadata={"connection_id": str(connection_id), "job_id": str(job.id)},
        )
        return run

    # -- runs ---------------------------------------------------------------

    async def cancel_run(
        self, session: AsyncSession, *, organization_id: UUID, run_id: UUID
    ) -> ConnectorSyncRun:
        run = await self.require_sync_run(session, organization_id, run_id)
        if run.status not in ACTIVE_RUN_STATUSES:
            raise SyncEngineError(f"sync run {run_id} is already in terminal state '{run.status}'")
        run.status = ConnectorSyncRunStatus.cancelled.value
        run.completed_at = datetime.now(UTC)
        run.error_message = "Cancelled by user"
        await session.flush()
        await session.refresh(run)
        return run

    async def get_sync_run(
        self, session: AsyncSession, *, organization_id: UUID, run_id: UUID
    ) -> ConnectorSyncRun | None:
        result = await session.execute(
            select(ConnectorSyncRun)
            .options(
                selectinload(ConnectorSyncRun.connection).selectinload(ConnectorConnection.provider)
            )
            .where(
                ConnectorSyncRun.id == run_id,
                ConnectorSyncRun.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_sync_runs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        limit: int = 20,
    ) -> list[ConnectorSyncRun]:
        result = await session.execute(
            select(ConnectorSyncRun)
            .where(
                ConnectorSyncRun.organization_id == organization_id,
                ConnectorSyncRun.connection_id == connection_id,
            )
            .order_by(ConnectorSyncRun.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_queued_run(
        self, session: AsyncSession, *, job: ConnectorSyncJob, trigger_type: str
    ) -> ConnectorSyncRun:
        run = await self.engine.repository.create_sync_run(
            session,
            organization_id=job.organization_id,
            sync_job_id=job.id,
            connection_id=job.connection_id,
            sync_version=int(datetime.now(UTC).timestamp()),
            external_source_id=job.external_source_id,
            status=ConnectorSyncRunStatus.queued.value,
            cursor_before=dict(job.cursor_json or {}),
        )
        run.trigger_type = trigger_type
        await session.flush()
        await session.refresh(run)
        return run

    async def has_active_run(self, session: AsyncSession, *, job_id: UUID) -> bool:
        result = await session.execute(
            select(ConnectorSyncRun.id)
            .where(
                ConnectorSyncRun.sync_job_id == job_id,
                ConnectorSyncRun.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def assert_no_active_run(self, session: AsyncSession, *, job_id: UUID) -> None:
        if await self.has_active_run(session, job_id=job_id):
            raise SyncEngineError(
                "sync is already queued or running for this job; cancel or wait for it to finish"
            )

    async def require_sync_job(
        self, session: AsyncSession, organization_id: UUID, job_id: UUID
    ) -> ConnectorSyncJob:
        job = await self.get_sync_job(session, organization_id=organization_id, job_id=job_id)
        if job is None:
            raise SyncEngineError(f"sync job {job_id} not found")
        return job

    async def require_sync_run(
        self, session: AsyncSession, organization_id: UUID, run_id: UUID
    ) -> ConnectorSyncRun:
        run = await self.get_sync_run(session, organization_id=organization_id, run_id=run_id)
        if run is None:
            raise SyncEngineError(f"sync run {run_id} not found")
        return run
