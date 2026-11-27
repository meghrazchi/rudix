"""Generic connector sync engine: job lifecycle, checkpointing, scheduling.

``ConnectorSyncEngine`` is a facade over ``app.domains.connectors.services.sync``
(R06-11): ``planner`` (jobs, triggers, runs), ``scheduler`` (due-job polling),
``runner`` (run execution), ``fetcher`` (provider paging, OAuth refresh), ``differ``
(change detection, conflicts, tombstones), and ``writer`` (file ingestion, run outcomes,
audit). The components read the engine's collaborators at call time, so tests may
replace ``ingestion_bridge`` or ``credential_vault`` after construction.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.services.audit_service import AuditLogService
from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.services.credential_vault import CredentialVault
from app.domains.connectors.services.provider_adapter import (
    DeltaItem,
    SyncAdapterRegistry,
    default_sync_adapter_registry,
)
from app.domains.connectors.services.sync.common import (
    DEFAULT_PAGE_SIZE,
    FILE_ITEM_TYPES,
    SyncEngineError,
    SyncRunResult,
    compute_content_hash,
    next_run_due,
)
from app.domains.connectors.services.sync.differ import SyncDiffer
from app.domains.connectors.services.sync.fetcher import SyncFetcher
from app.domains.connectors.services.sync.planner import SyncPlanner
from app.domains.connectors.services.sync.runner import SyncRunner
from app.domains.connectors.services.sync.schedule import SyncScheduler
from app.domains.connectors.services.sync.writer import SyncWriter
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.connector_credential import ConnectorCredential
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import ConnectorSyncJobStatus

if TYPE_CHECKING:
    from app.domains.connectors.services.ingestion_bridge import ConnectorIngestionBridge
    from app.domains.connectors.services.oauth_lifecycle import ConnectorOAuthLifecycleService

__all__ = [
    "ConnectorSyncEngine",
    "SyncEngineError",
    "SyncRunResult",
    "_compute_content_hash",
    "_next_run_due",
]

# Compatibility names (imported by tests and older callers).
_DEFAULT_PAGE_SIZE = DEFAULT_PAGE_SIZE
_FILE_ITEM_TYPES = FILE_ITEM_TYPES


def _next_run_due(job: ConnectorSyncJob, now: datetime) -> bool:
    return next_run_due(job, now)


def _compute_content_hash(data: Any) -> str:
    return compute_content_hash(data)


class ConnectorSyncEngine:
    def __init__(
        self,
        *,
        repository: ConnectorRepository | None = None,
        adapter_registry: SyncAdapterRegistry | None = None,
        credential_vault: CredentialVault | None = None,
        ingestion_bridge: ConnectorIngestionBridge | None = None,
        audit_service: AuditLogService | None = None,
        oauth_lifecycle: ConnectorOAuthLifecycleService | None = None,
    ) -> None:
        self.repository = repository or ConnectorRepository()
        self.adapter_registry = adapter_registry or default_sync_adapter_registry
        self.credential_vault = credential_vault or CredentialVault()
        self.ingestion_bridge = ingestion_bridge
        self.audit_service = audit_service or AuditLogService()
        self._oauth_lifecycle = oauth_lifecycle
        self.planner = SyncPlanner(self)
        self.scheduler = SyncScheduler(self)
        self.runner = SyncRunner(self)
        self.fetcher = SyncFetcher(self)
        self.differ = SyncDiffer(self)
        self.writer = SyncWriter(self)

    # -- jobs -------------------------------------------------------------------

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
        return await self.planner.create_sync_job(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            name=name,
            user_id=user_id,
            external_source_id=external_source_id,
            collection_id=collection_id,
            schedule=schedule,
        )

    async def update_sync_job_status(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        job_id: UUID,
        status: ConnectorSyncJobStatus,
        user_id: UUID | None = None,
    ) -> ConnectorSyncJob:
        return await self.planner.update_sync_job_status(
            session, organization_id=organization_id, job_id=job_id, status=status, user_id=user_id
        )

    async def get_sync_job(
        self, session: AsyncSession, *, organization_id: UUID, job_id: UUID
    ) -> ConnectorSyncJob | None:
        return await self.planner.get_sync_job(
            session, organization_id=organization_id, job_id=job_id
        )

    async def list_sync_jobs(
        self, session: AsyncSession, *, organization_id: UUID, connection_id: UUID
    ) -> list[ConnectorSyncJob]:
        return await self.planner.list_sync_jobs(
            session, organization_id=organization_id, connection_id=connection_id
        )

    # -- runs -------------------------------------------------------------------

    async def trigger_manual_sync(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        job_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> ConnectorSyncRun:
        return await self.planner.trigger_manual_sync(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
        )

    async def retry_failed_sync(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        run_id: UUID,
        user_id: UUID | None = None,
    ) -> ConnectorSyncRun:
        return await self.planner.retry_failed_sync(
            session, organization_id=organization_id, run_id=run_id, user_id=user_id
        )

    async def trigger_full_resync(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        job_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> ConnectorSyncRun:
        return await self.planner.trigger_full_resync(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            job_id=job_id,
            user_id=user_id,
        )

    async def cancel_run(
        self, session: AsyncSession, *, organization_id: UUID, run_id: UUID
    ) -> ConnectorSyncRun:
        return await self.planner.cancel_run(
            session, organization_id=organization_id, run_id=run_id
        )

    async def get_sync_run(
        self, session: AsyncSession, *, organization_id: UUID, run_id: UUID
    ) -> ConnectorSyncRun | None:
        return await self.planner.get_sync_run(
            session, organization_id=organization_id, run_id=run_id
        )

    async def list_sync_runs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        limit: int = 20,
    ) -> list[ConnectorSyncRun]:
        return await self.planner.list_sync_runs(
            session, organization_id=organization_id, connection_id=connection_id, limit=limit
        )

    async def dispatch_due_syncs(self, session: AsyncSession) -> list[tuple[UUID, UUID]]:
        return await self.scheduler.dispatch_due_syncs(session)

    async def run_sync(
        self, session: AsyncSession, *, sync_run_id: UUID, organization_id: UUID
    ) -> SyncRunResult:
        return await self.runner.run_sync(
            session, sync_run_id=sync_run_id, organization_id=organization_id
        )

    # -- internal seams (kept for tests and the worker) -------------------------

    async def _run_full_sync(self, session: AsyncSession, **kwargs: Any) -> SyncRunResult:
        return await self.runner.run_full_sync(session, **kwargs)

    async def _run_incremental_sync(self, session: AsyncSession, **kwargs: Any) -> SyncRunResult:
        return await self.runner.run_incremental_sync(session, **kwargs)

    async def _upsert_item_if_changed(
        self, session: AsyncSession, run: ConnectorSyncRun, norm_item: Any
    ) -> bool:
        return await self.differ.upsert_item_if_changed(session, run, norm_item)

    async def _tombstone_unseen_items(
        self, session: AsyncSession, *, run: ConnectorSyncRun, seen_provider_ids: set[str]
    ) -> int:
        return await self.differ.tombstone_unseen_items(
            session, run=run, seen_provider_ids=seen_provider_ids
        )

    async def _tombstone_item(
        self, session: AsyncSession, run: ConnectorSyncRun, delta_item: DeltaItem
    ) -> bool:
        return await self.differ.tombstone_item(session, run, delta_item)

    async def _record_conflict(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        external_item: ExternalItem,
        conflict_type: str,
        detail: dict,
    ) -> None:
        await self.differ.record_conflict(
            session,
            run=run,
            external_item=external_item,
            conflict_type=conflict_type,
            detail=detail,
        )

    async def _maybe_ingest_file_item(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        connection: ConnectorConnection,
        adapter: Any,
        norm_item: Any,
        decrypted_credential: dict,
    ) -> tuple[str, str] | None:
        return await self.writer.maybe_ingest_file_item(
            session,
            run=run,
            connection=connection,
            adapter=adapter,
            norm_item=norm_item,
            decrypted_credential=decrypted_credential,
        )

    async def _flush_run_progress(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        *,
        items_seen: int,
        items_upserted: int,
        items_deleted: int = 0,
    ) -> None:
        await self.writer.flush_run_progress(
            session,
            run,
            items_seen=items_seen,
            items_upserted=items_upserted,
            items_deleted=items_deleted,
        )

    async def _complete_run(
        self, session: AsyncSession, run: ConnectorSyncRun, **kwargs: Any
    ) -> SyncRunResult:
        return await self.writer.complete_run(session, run, **kwargs)

    async def _fail_run(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        message: str,
        *,
        error_code: str = "sync_error",
        error_details: dict | None = None,
    ) -> SyncRunResult:
        return await self.writer.fail_run(
            session, run, message, error_code=error_code, error_details=error_details
        )

    async def _audit(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        metadata: dict[str, object],
    ) -> None:
        await self.writer.audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
        )

    async def _cancel_run_in_flight(
        self, session: AsyncSession, run: ConnectorSyncRun, items_seen: int, items_upserted: int
    ) -> SyncRunResult:
        return await self.writer.cancel_run_in_flight(session, run, items_seen, items_upserted)

    async def _is_cancelled(self, session: AsyncSession, *, run_id: UUID) -> bool:
        return await self.writer.is_cancelled(session, run_id=run_id)

    async def _create_queued_run(
        self, session: AsyncSession, *, job: ConnectorSyncJob, trigger_type: str
    ) -> ConnectorSyncRun:
        return await self.planner.create_queued_run(session, job=job, trigger_type=trigger_type)

    async def _has_active_run(self, session: AsyncSession, *, job_id: UUID) -> bool:
        return await self.planner.has_active_run(session, job_id=job_id)

    async def _assert_no_active_run(self, session: AsyncSession, *, job_id: UUID) -> None:
        await self.planner.assert_no_active_run(session, job_id=job_id)

    async def _refresh_oauth_if_needed(
        self,
        session: AsyncSession,
        *,
        connection: ConnectorConnection,
        credential: ConnectorCredential,
        organization_id: UUID,
    ) -> ConnectorCredential:
        return await self.fetcher.refresh_oauth_if_needed(
            session, connection=connection, credential=credential, organization_id=organization_id
        )

    async def _mark_connection_error(
        self, session: AsyncSession, connection: ConnectorConnection, message: str
    ) -> None:
        await self.writer.mark_connection_error(session, connection, message)

    async def _require_sync_job(
        self, session: AsyncSession, organization_id: UUID, job_id: UUID
    ) -> ConnectorSyncJob:
        return await self.planner.require_sync_job(session, organization_id, job_id)

    async def _require_sync_run(
        self, session: AsyncSession, organization_id: UUID, run_id: UUID
    ) -> ConnectorSyncRun:
        return await self.planner.require_sync_run(session, organization_id, run_id)
