"""Generic connector sync engine: job lifecycle, checkpointing, scheduling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.domains.connectors.services.ingestion_bridge import ConnectorIngestionBridge
    from app.domains.connectors.services.oauth_lifecycle import ConnectorOAuthLifecycleService

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger, log_connector_event
from app.domains.admin.services.audit_service import AuditLogService, sanitize_metadata
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.services.credential_vault import CredentialVault
from app.domains.connectors.services.provider_adapter import (
    ConnectorAdapterNotFoundError,
    ConnectorAuthError,
    ConnectorContentError,
    ConnectorPermissionError,
    ConnectorRateLimitError,
    DeltaItem,
    SyncAdapterRegistry,
    default_sync_adapter_registry,
)
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.connector_credential import ConnectorCredential
from app.models.connector_source import SourceDocument
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import (
    ConnectorAuthType,
    ConnectorConnectionStatus,
    ConnectorCredentialStatus,
    ConnectorSyncJobStatus,
    ConnectorSyncRunStatus,
    ExternalItemType,
    SyncConflictType,
)

_logger = get_logger("connectors.sync_engine")

_DEFAULT_PAGE_SIZE = 100
_MAX_SCHEDULE_LOOKBACK_DAYS = 7

# Item types whose content should be downloaded and ingested as Documents.
_FILE_ITEM_TYPES: frozenset[str] = frozenset(
    {ExternalItemType.cloud_file, ExternalItemType.attachment, ExternalItemType.wiki_page}
)


@dataclass
class SyncRunResult:
    sync_run_id: UUID
    status: str
    items_seen: int
    items_upserted: int
    items_deleted: int
    cursor_after: dict
    error_message: str | None = None
    pending_document_ids: list[tuple[str, str]] = field(default_factory=list)


class SyncEngineError(Exception):
    """Raised for engine-level validation failures (not task-level retries)."""


def _next_run_due(job: ConnectorSyncJob, now: datetime) -> bool:
    schedule = job.schedule_json or {}
    schedule_type = schedule.get("type", "interval")
    if schedule_type == "manual_only":
        return False
    interval_minutes = int(schedule.get("interval_minutes", 60))
    interval_minutes = max(5, min(interval_minutes, 60 * 24 * 7))
    if job.last_run_at is None:
        return True
    last_run = job.last_run_at
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=UTC)
    return now >= last_run + timedelta(minutes=interval_minutes)


def _compute_content_hash(data: Any) -> str:
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


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

    # -----------------------------------------------------------------------
    # Job management
    # -----------------------------------------------------------------------

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
        connection = await self.repository.get_connection(
            session, organization_id=organization_id, connection_id=connection_id
        )
        if connection is None:
            raise SyncEngineError("connector connection not found")
        job = await self.repository.create_sync_job(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            name=name,
            external_source_id=external_source_id,
            collection_id=collection_id,
            schedule=schedule or {"type": "interval", "interval_minutes": 60},
        )
        if external_source_id is not None:
            await self._audit(
                session,
                organization_id=organization_id,
                user_id=user_id,
                action=ConnectorAuditAction.source_selected.value,
                resource_type="connector_sync_job",
                resource_id=job.id,
                metadata={
                    "connection_id": str(connection_id),
                    "external_source_id": str(external_source_id),
                    "collection_id": str(collection_id) if collection_id else None,
                    "job_name": name,
                },
            )
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.sync_job_created.value,
            resource_type="connector_sync_job",
            resource_id=job.id,
            metadata={
                "connection_id": str(connection_id),
                "external_source_id": str(external_source_id) if external_source_id else None,
                "collection_id": str(collection_id) if collection_id else None,
                "job_name": name,
            },
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
        job = await self._require_sync_job(session, organization_id, job_id)
        job.status = status.value
        await session.flush()
        await session.refresh(job)
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.sync_job_status_changed.value,
            resource_type="connector_sync_job",
            resource_id=job.id,
            metadata={
                "connection_id": str(job.connection_id),
                "status": status.value,
            },
        )
        return job

    async def get_sync_job(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        job_id: UUID,
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
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
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

    # -----------------------------------------------------------------------
    # Run management
    # -----------------------------------------------------------------------

    async def trigger_manual_sync(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        job_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> ConnectorSyncRun:
        job: ConnectorSyncJob | None
        if job_id is not None:
            job = await self._require_sync_job(session, organization_id, job_id)
        else:
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
            if job is None:
                connection = await self.repository.get_connection(
                    session, organization_id=organization_id, connection_id=connection_id
                )
                if connection is None:
                    raise SyncEngineError("connector connection not found")
                job = await self.repository.create_sync_job(
                    session,
                    organization_id=organization_id,
                    connection_id=connection_id,
                    name=f"{connection.display_name} — default sync",
                    schedule={"type": "interval", "interval_minutes": 60},
                )
        assert job is not None

        await self._assert_no_active_run(session, job_id=job.id)
        run = await self._create_queued_run(session, job=job, trigger_type="manual")
        await self._audit(
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
        run = await self._require_sync_run(session, organization_id, run_id)
        if run.status != ConnectorSyncRunStatus.failed.value:
            raise SyncEngineError(f"sync run {run_id} is not in failed state")

        job = await self._require_sync_job(session, organization_id, run.sync_job_id)
        connection = await self.repository.get_connection(
            session,
            organization_id=organization_id,
            connection_id=run.connection_id,
        )
        if connection is None:
            raise SyncEngineError("connector connection not found")
        if connection.status != ConnectorConnectionStatus.active.value:
            raise SyncEngineError(f"connection is not active (status={connection.status})")
        if job.status == ConnectorSyncJobStatus.disabled.value:
            raise SyncEngineError("sync job is disabled")

        await self._assert_no_active_run(session, job_id=job.id)
        retry_run = await self.repository.create_sync_run(
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
        await self._audit(
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
        job: ConnectorSyncJob | None
        if job_id is not None:
            job = await self._require_sync_job(session, organization_id, job_id)
        else:
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
            if job is None:
                connection = await self.repository.get_connection(
                    session, organization_id=organization_id, connection_id=connection_id
                )
                if connection is None:
                    raise SyncEngineError("connector connection not found")
                job = await self.repository.create_sync_job(
                    session,
                    organization_id=organization_id,
                    connection_id=connection_id,
                    name=f"{connection.display_name} — default sync",
                    schedule={"type": "interval", "interval_minutes": 60},
                )
        assert job is not None

        await self._assert_no_active_run(session, job_id=job.id)
        # Wipe the cursor so the next run is a full sync regardless of prior state.
        job.cursor_json = {}
        await session.flush()

        run = await self._create_queued_run(session, job=job, trigger_type="manual")
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.sync_full_resync_triggered.value,
            resource_type="connector_sync_run",
            resource_id=run.id,
            metadata={
                "connection_id": str(connection_id),
                "job_id": str(job.id),
            },
        )
        return run

    async def cancel_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        run_id: UUID,
    ) -> ConnectorSyncRun:
        run = await self._require_sync_run(session, organization_id, run_id)
        if run.status not in {
            ConnectorSyncRunStatus.queued.value,
            ConnectorSyncRunStatus.running.value,
        }:
            raise SyncEngineError(f"sync run {run_id} is already in terminal state '{run.status}'")
        run.status = ConnectorSyncRunStatus.cancelled.value
        run.completed_at = datetime.now(UTC)
        run.error_message = "Cancelled by user"
        await session.flush()
        await session.refresh(run)
        return run

    async def get_sync_run(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        run_id: UUID,
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

    # -----------------------------------------------------------------------
    # Schedule polling (called by beat task)
    # -----------------------------------------------------------------------

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
        for job in jobs:
            if not _next_run_due(job, now):
                continue
            has_active = await self._has_active_run(session, job_id=job.id)
            if has_active:
                continue
            run = await self._create_queued_run(session, job=job, trigger_type="scheduled")
            dispatched.append((run.id, job.organization_id))
        if dispatched:
            await session.flush()
        return dispatched

    # -----------------------------------------------------------------------
    # Core sync execution (called by Celery task)
    # -----------------------------------------------------------------------

    async def run_sync(
        self,
        session: AsyncSession,
        *,
        sync_run_id: UUID,
        organization_id: UUID,
    ) -> SyncRunResult:
        """Execute a single sync run through its complete lifecycle."""
        run = await self._require_sync_run(session, organization_id, sync_run_id)

        if run.status == ConnectorSyncRunStatus.cancelled.value:
            return SyncRunResult(
                sync_run_id=run.id,
                status="cancelled",
                items_seen=0,
                items_upserted=0,
                items_deleted=0,
                cursor_after={},
                error_message="Run was cancelled before it started",
            )

        # Mark running
        run.status = ConnectorSyncRunStatus.running.value
        run.started_at = datetime.now(UTC)
        await session.flush()
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=None,
            action=ConnectorAuditAction.sync_started.value,
            resource_type="connector_sync_run",
            resource_id=run.id,
            metadata={
                "sync_job_id": str(run.sync_job_id),
                "connection_id": str(run.connection_id),
                "external_source_id": (
                    str(run.external_source_id) if run.external_source_id else None
                ),
                "trigger_type": run.trigger_type,
            },
        )

        job_result = await session.execute(
            select(ConnectorSyncJob)
            .options(
                selectinload(ConnectorSyncJob.connection).selectinload(ConnectorConnection.provider)
            )
            .where(ConnectorSyncJob.id == run.sync_job_id)
        )
        job = job_result.scalar_one_or_none()
        if job is None:
            return await self._fail_run(session, run, "sync job not found")

        connection = job.connection
        if connection.status != ConnectorConnectionStatus.active.value:
            return await self._fail_run(
                session,
                run,
                f"connection is not active (status={connection.status})",
                error_code="connection_not_active",
            )

        # Resolve credential
        credential = await self.repository.get_current_credential(
            session,
            organization_id=organization_id,
            connection_id=connection.id,
        )
        if credential is None:
            return await self._fail_run(session, run, "no credential found for connection")
        if credential.status == ConnectorCredentialStatus.revoked.value:
            return await self._fail_run(session, run, "credential has been revoked")

        credential = await self._refresh_oauth_if_needed(
            session, connection=connection, credential=credential, organization_id=organization_id
        )

        try:
            decrypted = self.credential_vault.decrypt(credential)
        except Exception as exc:
            return await self._fail_run(session, run, f"credential decryption failed: {exc}")

        try:
            adapter = self.adapter_registry.require(connection.provider.key)
        except ConnectorAdapterNotFoundError as exc:
            return await self._fail_run(session, run, str(exc), error_code="adapter_not_found")

        # Choose incremental vs full based on cursor
        cursor_before = dict(run.cursor_before_json or {})
        use_incremental = bool(cursor_before) and hasattr(adapter, "delta_sync")

        try:
            if use_incremental:
                result = await self._run_incremental_sync(
                    session,
                    run=run,
                    job=job,
                    connection=connection,
                    adapter=adapter,
                    decrypted_credential=decrypted,
                    cursor=cursor_before,
                )
            else:
                result = await self._run_full_sync(
                    session,
                    run=run,
                    job=job,
                    connection=connection,
                    adapter=adapter,
                    decrypted_credential=decrypted,
                )
        except ConnectorAuthError as exc:
            # For OAuth connections: attempt a token refresh + one retry before giving up.
            # This handles expired tokens regardless of whether expires_at is set in the DB.
            retry_result = await self._refresh_and_retry(
                session,
                run=run,
                job=job,
                connection=connection,
                adapter=adapter,
                credential=credential,
                organization_id=organization_id,
                cursor_before=cursor_before,
                use_incremental=use_incremental,
            )
            if retry_result is not None:
                result = retry_result
            else:
                await self._mark_connection_error(session, connection, str(exc))
                return await self._fail_run(session, run, str(exc), error_code="auth_error")
        except ConnectorRateLimitError as exc:
            return await self._fail_run(
                session,
                run,
                str(exc),
                error_code="rate_limit",
                error_details={"retry_after_seconds": exc.retry_after_seconds},
            )
        except ConnectorPermissionError as exc:
            return await self._fail_run(
                session,
                run,
                "permission denied",
                error_code="permission_denied",
                error_details={"reason": exc.__class__.__name__},
            )
        except Exception as exc:
            return await self._fail_run(session, run, str(exc))

        # Update job and connection after successful run
        now = datetime.now(UTC)
        job.last_run_at = now
        job.cursor_json = result.cursor_after
        job.error_message = None
        connection.last_sync_at = now
        await session.flush()
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=None,
            action=ConnectorAuditAction.sync_succeeded.value,
            resource_type="connector_sync_run",
            resource_id=run.id,
            metadata={
                "sync_job_id": str(run.sync_job_id),
                "connection_id": str(connection.id),
                "items_seen": result.items_seen,
                "items_upserted": result.items_upserted,
                "items_deleted": result.items_deleted,
                "trigger_type": run.trigger_type,
            },
        )
        log_connector_event(
            event="connector.sync.completed",
            provider_key=getattr(getattr(connection, "provider", None), "key", None),
            connection_id=str(connection.id),
            external_source_id=str(run.external_source_id) if run.external_source_id else None,
            sync_run_id=str(run.id),
            organization_id=str(organization_id),
            items_seen=result.items_seen,
            items_upserted=result.items_upserted,
            items_deleted=result.items_deleted,
        )
        _logger.info(
            "connector.sync.completed",
            sync_run_id=str(sync_run_id),
            provider_key=getattr(connection.provider, "key", None),
            connection_id=str(connection.id),
            external_source_id=str(run.external_source_id) if run.external_source_id else None,
            organization_id=str(organization_id),
            items_seen=result.items_seen,
            items_upserted=result.items_upserted,
            items_deleted=result.items_deleted,
        )
        return result

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _run_full_sync(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        job: ConnectorSyncJob,
        connection: ConnectorConnection,
        adapter: Any,
        decrypted_credential: dict,
    ) -> SyncRunResult:
        items_seen = 0
        items_upserted = 0
        cursor: dict = {}
        seen_provider_ids: set[str] = set()
        pending_document_ids: list[tuple[str, str]] = []

        while True:
            if await self._is_cancelled(session, run_id=run.id):
                return await self._cancel_run_in_flight(session, run, items_seen, items_upserted)

            page = await adapter.list_items(
                organization_id=str(run.organization_id),
                connection_id=str(run.connection_id),
                external_source_id=str(run.external_source_id) if run.external_source_id else None,
                provider_source_id=(
                    job.external_source.provider_source_id
                    if job.external_source_id
                    and hasattr(job, "external_source")
                    and job.external_source
                    else None
                ),
                decrypted_credential=decrypted_credential,
                cursor=cursor,
                page_size=_DEFAULT_PAGE_SIZE,
            )

            for norm_item in page.items:
                items_seen += 1
                seen_provider_ids.add(norm_item.provider_item_id)
                changed = await self._upsert_item_if_changed(session, run, norm_item)
                if changed:
                    items_upserted += 1
                    pending = await self._maybe_ingest_file_item(
                        session,
                        run=run,
                        connection=connection,
                        adapter=adapter,
                        norm_item=norm_item,
                        decrypted_credential=decrypted_credential,
                    )
                    if pending is not None:
                        pending_document_ids.append(pending)

            await self._flush_run_progress(
                session, run, items_seen=items_seen, items_upserted=items_upserted
            )
            if not page.has_more or page.next_cursor is None:
                break
            cursor = page.next_cursor

        items_deleted = await self._tombstone_unseen_items(
            session, run=run, seen_provider_ids=seen_provider_ids
        )

        return await self._complete_run(
            session,
            run,
            items_seen=items_seen,
            items_upserted=items_upserted,
            items_deleted=items_deleted,
            cursor_after=cursor,
            pending_document_ids=pending_document_ids,
        )

    async def _run_incremental_sync(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        job: ConnectorSyncJob,
        connection: ConnectorConnection,
        adapter: Any,
        decrypted_credential: dict,
        cursor: dict,
    ) -> SyncRunResult:
        items_seen = 0
        items_upserted = 0
        items_deleted = 0
        pending_document_ids: list[tuple[str, str]] = []

        while True:
            if await self._is_cancelled(session, run_id=run.id):
                return await self._cancel_run_in_flight(session, run, items_seen, items_upserted)

            page = await adapter.delta_sync(
                organization_id=str(run.organization_id),
                connection_id=str(run.connection_id),
                external_source_id=str(run.external_source_id) if run.external_source_id else None,
                provider_source_id=(
                    job.external_source.provider_source_id
                    if job.external_source_id
                    and hasattr(job, "external_source")
                    and job.external_source
                    else None
                ),
                decrypted_credential=decrypted_credential,
                cursor=cursor,
                page_size=_DEFAULT_PAGE_SIZE,
            )

            for delta_item in page.items:
                items_seen += 1
                if delta_item.is_deleted or delta_item.permission_revoked:
                    deleted = await self._tombstone_item(session, run, delta_item)
                    if deleted:
                        items_deleted += 1
                elif delta_item.item is not None:
                    try:
                        changed = await self._upsert_item_if_changed(session, run, delta_item.item)
                        if changed:
                            items_upserted += 1
                            pending = await self._maybe_ingest_file_item(
                                session,
                                run=run,
                                connection=connection,
                                adapter=adapter,
                                norm_item=delta_item.item,
                                decrypted_credential=decrypted_credential,
                            )
                            if pending is not None:
                                pending_document_ids.append(pending)
                    except ConnectorContentError:
                        await self._audit(
                            session,
                            organization_id=run.organization_id,
                            user_id=None,
                            action=ConnectorAuditAction.sync_item_skipped.value,
                            resource_type="external_item",
                            resource_id=None,
                            metadata={
                                "sync_run_id": str(run.id),
                                "connection_id": str(run.connection_id),
                                "external_source_id": (
                                    str(run.external_source_id) if run.external_source_id else None
                                ),
                                "provider_key": delta_item.item.provider_key,
                                "provider_item_id": delta_item.item.provider_item_id,
                                "reason": "content_error",
                            },
                        )
                        log_connector_event(
                            event="connector.sync.item.skipped",
                            provider_key=delta_item.item.provider_key,
                            connection_id=str(run.connection_id),
                            external_source_id=(
                                str(run.external_source_id) if run.external_source_id else None
                            ),
                            external_item_id=None,
                            sync_run_id=str(run.id),
                            organization_id=str(run.organization_id),
                            reason="content_error",
                        )

            await self._flush_run_progress(
                session,
                run,
                items_seen=items_seen,
                items_upserted=items_upserted,
                items_deleted=items_deleted,
            )
            if not page.has_more or page.next_cursor is None:
                cursor = page.next_cursor or cursor
                break
            cursor = page.next_cursor

        return await self._complete_run(
            session,
            run,
            items_seen=items_seen,
            items_upserted=items_upserted,
            items_deleted=items_deleted,
            cursor_after=cursor,
            pending_document_ids=pending_document_ids,
        )

    async def _upsert_item_if_changed(
        self, session: AsyncSession, run: ConnectorSyncRun, norm_item: Any
    ) -> bool:
        norm_item_with_version = norm_item.model_copy(update={"sync_version": run.sync_version})
        existing_result = await session.execute(
            select(ExternalItem).where(
                ExternalItem.organization_id == run.organization_id,
                ExternalItem.connection_id == run.connection_id,
                ExternalItem.provider_item_id == norm_item.provider_item_id,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None and existing.content_hash == norm_item.content_hash:
            existing.sync_version = run.sync_version

            # Detect ACL drift even when content is unchanged.
            new_acl = getattr(norm_item, "acl_hash", None)
            if new_acl and existing.acl_hash and new_acl != existing.acl_hash:
                await self._record_conflict(
                    session,
                    run=run,
                    external_item=existing,
                    conflict_type=SyncConflictType.acl_changed.value,
                    detail={
                        "previous_acl_hash": existing.acl_hash,
                        "new_acl_hash": new_acl,
                        "provider_item_id": norm_item.provider_item_id,
                    },
                )

            # Detect rename (title changed) or move (parent_id changed).
            new_parent = getattr(norm_item, "provider_parent_id", None)
            if (
                existing.provider_parent_id
                and new_parent
                and new_parent != existing.provider_parent_id
            ):
                await self._record_conflict(
                    session,
                    run=run,
                    external_item=existing,
                    conflict_type=SyncConflictType.moved.value,
                    detail={
                        "previous_parent_id": existing.provider_parent_id,
                        "new_parent_id": new_parent,
                        "provider_item_id": norm_item.provider_item_id,
                    },
                )
            elif existing.title and norm_item.title and norm_item.title != existing.title:
                await self._record_conflict(
                    session,
                    run=run,
                    external_item=existing,
                    conflict_type=SyncConflictType.renamed.value,
                    detail={
                        "previous_title": existing.title,
                        "new_title": norm_item.title,
                        "provider_item_id": norm_item.provider_item_id,
                    },
                )

            await session.flush()
            # Treat as changed if no SourceDocument exists yet (e.g. prior sync had no bridge).
            orphaned_result = await session.execute(
                select(SourceDocument)
                .where(SourceDocument.external_item_id == existing.id)
                .limit(1)
            )
            if orphaned_result.scalar_one_or_none() is None:
                return True
            return False

        await self.repository.upsert_external_item(session, item=norm_item_with_version)
        return True

    async def _tombstone_unseen_items(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        seen_provider_ids: set[str],
    ) -> int:
        result = await session.execute(
            select(ExternalItem).where(
                ExternalItem.organization_id == run.organization_id,
                ExternalItem.connection_id == run.connection_id,
                ExternalItem.deleted_at.is_(None),
                ExternalItem.sync_version < run.sync_version,
            )
        )
        stale_items = list(result.scalars().all())
        count = 0
        now = datetime.now(UTC)
        for item in stale_items:
            if item.provider_item_id not in seen_provider_ids:
                item.deleted_at = now
                await self.repository.record_tombstone(
                    session,
                    organization_id=run.organization_id,
                    connection_id=run.connection_id,
                    provider_item_id=item.provider_item_id,
                    tombstoned_at=now,
                    external_source_id=run.external_source_id,
                    sync_run_id=run.id,
                    item_type=item.item_type,
                    source_url=item.source_url,
                    last_seen_sync_version=item.sync_version,
                    reason="not_seen_in_full_sync",
                )
                await self._audit(
                    session,
                    organization_id=run.organization_id,
                    user_id=None,
                    action=ConnectorAuditAction.source_deleted.value,
                    resource_type="external_item",
                    resource_id=item.id,
                    metadata={
                        "connection_id": str(run.connection_id),
                        "external_source_id": (
                            str(run.external_source_id) if run.external_source_id else None
                        ),
                        "provider_item_id": item.provider_item_id,
                        "reason": "not_seen_in_full_sync",
                    },
                )
                count += 1
        return count

    async def _tombstone_item(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        delta_item: DeltaItem,
    ) -> bool:
        result = await session.execute(
            select(ExternalItem).where(
                ExternalItem.organization_id == run.organization_id,
                ExternalItem.connection_id == run.connection_id,
                ExternalItem.provider_item_id == delta_item.provider_item_id,
                ExternalItem.deleted_at.is_(None),
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return False
        now = datetime.now(UTC)

        reason = "permission_revoked" if delta_item.permission_revoked else "provider_deleted"

        # Permission revocations are recorded as open conflicts — the document
        # still exists remotely but is no longer accessible to this connection.
        # We tombstone the item AND create a conflict so an admin can act.
        if delta_item.permission_revoked:
            await self._record_conflict(
                session,
                run=run,
                external_item=item,
                conflict_type=SyncConflictType.permission_revoked.value,
                detail={
                    "provider_item_id": delta_item.provider_item_id,
                    "item_type": item.item_type,
                    "source_url": item.source_url,
                },
            )

        item.deleted_at = now
        await self.repository.record_tombstone(
            session,
            organization_id=run.organization_id,
            connection_id=run.connection_id,
            provider_item_id=delta_item.provider_item_id,
            tombstoned_at=now,
            external_source_id=run.external_source_id,
            sync_run_id=run.id,
            item_type=item.item_type,
            source_url=item.source_url,
            last_seen_sync_version=item.sync_version,
            reason=reason,
        )
        await self._audit(
            session,
            organization_id=run.organization_id,
            user_id=None,
            action=ConnectorAuditAction.source_deleted.value,
            resource_type="external_item",
            resource_id=item.id,
            metadata={
                "connection_id": str(run.connection_id),
                "external_source_id": str(run.external_source_id)
                if run.external_source_id
                else None,
                "provider_item_id": delta_item.provider_item_id,
                "reason": reason,
            },
        )
        return True

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
        """Download and ingest a file-type ExternalItem through the document lifecycle.

        Returns (document_id, user_id) when a document is ready for processing so the
        caller can dispatch the task AFTER the transaction commits. Returns None on skip.
        """
        if self.ingestion_bridge is None:
            return None
        if norm_item.item_type not in _FILE_ITEM_TYPES:
            return None

        ext_item_result = await session.execute(
            select(ExternalItem).where(
                ExternalItem.organization_id == run.organization_id,
                ExternalItem.connection_id == run.connection_id,
                ExternalItem.provider_item_id == norm_item.provider_item_id,
            )
        )
        ext_item = ext_item_result.scalar_one_or_none()

        try:
            download = await adapter.download_file_content(
                provider_item_id=norm_item.provider_item_id,
                mime_type=norm_item.mime_type,
                decrypted_credential=decrypted_credential,
            )
        except Exception as exc:
            await self._audit(
                session,
                organization_id=run.organization_id,
                user_id=None,
                action=ConnectorAuditAction.ingestion_failed.value,
                resource_type="external_item",
                resource_id=ext_item.id if ext_item is not None else None,
                metadata={
                    "sync_run_id": str(run.id),
                    "connection_id": str(run.connection_id),
                    "external_source_id": (
                        str(run.external_source_id) if run.external_source_id else None
                    ),
                    "provider_key": norm_item.provider_key,
                    "provider_item_id": norm_item.provider_item_id,
                    "reason": "download_failed",
                    "error": exc.__class__.__name__,
                },
            )
            log_connector_event(
                event="connector.ingestion.download_failed",
                provider_key=norm_item.provider_key,
                connection_id=str(run.connection_id),
                external_source_id=(
                    str(run.external_source_id) if run.external_source_id else None
                ),
                external_item_id=str(ext_item.id) if ext_item is not None else None,
                sync_run_id=str(run.id),
                organization_id=str(run.organization_id),
                error=exc.__class__.__name__,
            )
            _logger.warning(
                "connector.ingestion.download_failed",
                provider_item_id=norm_item.provider_item_id,
                error=str(exc)[:200],
            )
            return None

        if download is None:
            await self._audit(
                session,
                organization_id=run.organization_id,
                user_id=None,
                action=ConnectorAuditAction.ingestion_skipped.value,
                resource_type="external_item",
                resource_id=ext_item.id if ext_item is not None else None,
                metadata={
                    "sync_run_id": str(run.id),
                    "connection_id": str(run.connection_id),
                    "external_source_id": (
                        str(run.external_source_id) if run.external_source_id else None
                    ),
                    "provider_key": norm_item.provider_key,
                    "provider_item_id": norm_item.provider_item_id,
                    "reason": "download_not_available",
                },
            )
            log_connector_event(
                event="connector.ingestion.skipped",
                provider_key=norm_item.provider_key,
                connection_id=str(run.connection_id),
                external_source_id=(
                    str(run.external_source_id) if run.external_source_id else None
                ),
                external_item_id=str(ext_item.id) if ext_item is not None else None,
                sync_run_id=str(run.id),
                organization_id=str(run.organization_id),
                reason="download_not_available",
            )
            return None

        content, _provider_filename, resolved_mime = download

        # Use the human-readable source title as the filename, keeping the
        # extension that came back from the download (handles Google-native export).
        import os as _os

        _ext = _os.path.splitext(_provider_filename)[1]
        _title = (norm_item.title or "").strip()
        filename = _title if _title.lower().endswith(_ext.lower()) else f"{_title}{_ext}"

        uploader_user_id = connection.created_by_user_id
        if uploader_user_id is None:
            await self._audit(
                session,
                organization_id=run.organization_id,
                user_id=None,
                action=ConnectorAuditAction.ingestion_skipped.value,
                resource_type="external_item",
                resource_id=ext_item.id if ext_item is not None else None,
                metadata={
                    "sync_run_id": str(run.id),
                    "connection_id": str(run.connection_id),
                    "external_source_id": (
                        str(run.external_source_id) if run.external_source_id else None
                    ),
                    "provider_key": norm_item.provider_key,
                    "provider_item_id": norm_item.provider_item_id,
                    "reason": "missing_uploader_user",
                },
            )
            log_connector_event(
                event="connector.ingestion.skipped",
                provider_key=norm_item.provider_key,
                connection_id=str(connection.id),
                external_source_id=(
                    str(run.external_source_id) if run.external_source_id else None
                ),
                external_item_id=str(ext_item.id) if ext_item is not None else None,
                sync_run_id=str(run.id),
                organization_id=str(run.organization_id),
                reason="missing_uploader_user",
            )
            _logger.warning(
                "connector.ingestion.no_uploader_user",
                connection_id=str(connection.id),
                provider_item_id=norm_item.provider_item_id,
            )
            return None
        if ext_item is None:
            return None

        try:
            provenance_metadata = {
                **norm_item.metadata,
                "provider_key": norm_item.provider_key,
                "provider_item_id": norm_item.provider_item_id,
                "provider_label": getattr(connection.provider, "display_name", None),
                "source_title": norm_item.title,
                "source_url": norm_item.source_url,
                "source_item_type": norm_item.item_type.value,
                "source_item_content_hash": norm_item.content_hash,
                "source_item_sync_version": norm_item.sync_version,
                "sync_version": norm_item.sync_version,
                "acl_snapshot": norm_item.permissions,
                "trust_status": (
                    "trusted"
                    if norm_item.visibility.value == "org_wide" and not norm_item.permissions
                    else "restricted"
                ),
            }
            result = await self.ingestion_bridge.ingest_item(
                session,
                external_item_id=ext_item.id,
                organization_id=run.organization_id,
                collection_id=ext_item.collection_id,
                sync_run_id=run.id,
                uploader_user_id=uploader_user_id,
                content=content,
                filename=filename,
                mime_type=resolved_mime,
                source_url=norm_item.source_url,
                title=norm_item.title,
                metadata=provenance_metadata,
                sync_version=run.sync_version,
            )
            _logger.info(
                "connector.ingestion.result",
                provider_item_id=norm_item.provider_item_id,
                document_id=str(result.document_id) if result.document_id else None,
                status=result.status,
            )

            from app.models.enums import DocumentStatus as _DocumentStatus

            if result.status == _DocumentStatus.pending_scan and result.document_id is not None:
                return (str(result.document_id), str(uploader_user_id))
            return None
        except Exception as exc:
            await self._audit(
                session,
                organization_id=run.organization_id,
                user_id=None,
                action=ConnectorAuditAction.ingestion_failed.value,
                resource_type="external_item",
                resource_id=ext_item.id,
                metadata={
                    "sync_run_id": str(run.id),
                    "connection_id": str(run.connection_id),
                    "external_source_id": (
                        str(run.external_source_id) if run.external_source_id else None
                    ),
                    "provider_key": norm_item.provider_key,
                    "provider_item_id": norm_item.provider_item_id,
                    "reason": "bridge_error",
                    "error": exc.__class__.__name__,
                },
            )
            log_connector_event(
                event="connector.ingestion.bridge_error",
                provider_key=norm_item.provider_key,
                connection_id=str(run.connection_id),
                external_source_id=(
                    str(run.external_source_id) if run.external_source_id else None
                ),
                external_item_id=str(ext_item.id),
                sync_run_id=str(run.id),
                organization_id=str(run.organization_id),
                error=exc.__class__.__name__,
            )
            _logger.error(
                "connector.ingestion.bridge_error",
                provider_item_id=norm_item.provider_item_id,
                error=str(exc)[:300],
            )
        return None

    async def _record_conflict(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        external_item: ExternalItem,
        conflict_type: str,
        detail: dict,
    ) -> None:

        conflict = await self.repository.record_conflict(
            session,
            organization_id=run.organization_id,
            connection_id=run.connection_id,
            provider_item_id=external_item.provider_item_id,
            conflict_type=conflict_type,
            sync_run_id=run.id,
            external_item_id=external_item.id,
            conflict_detail=detail,
        )
        await self._audit(
            session,
            organization_id=run.organization_id,
            user_id=None,
            action=ConnectorAuditAction.sync_conflict_detected.value,
            resource_type="external_item",
            resource_id=external_item.id,
            metadata={
                "conflict_id": str(conflict.id),
                "conflict_type": conflict_type,
                "connection_id": str(run.connection_id),
                "provider_item_id": external_item.provider_item_id,
                "sync_run_id": str(run.id),
            },
        )
        log_connector_event(
            event="connector.sync.conflict.detected",
            provider_key=None,
            connection_id=str(run.connection_id),
            external_source_id=str(run.external_source_id) if run.external_source_id else None,
            external_item_id=str(external_item.id),
            sync_run_id=str(run.id),
            organization_id=str(run.organization_id),
            conflict_type=conflict_type,
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
        run.items_seen = items_seen
        run.items_upserted = items_upserted
        run.items_deleted = items_deleted
        await session.flush()

    async def _complete_run(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        *,
        items_seen: int,
        items_upserted: int,
        items_deleted: int,
        cursor_after: dict,
        pending_document_ids: list[tuple[str, str]] | None = None,
    ) -> SyncRunResult:
        now = datetime.now(UTC)
        run.status = ConnectorSyncRunStatus.completed.value
        run.completed_at = now
        run.items_seen = items_seen
        run.items_upserted = items_upserted
        run.items_deleted = items_deleted
        run.cursor_after_json = cursor_after
        run.error_message = None
        await session.flush()
        return SyncRunResult(
            sync_run_id=run.id,
            status="completed",
            items_seen=items_seen,
            items_upserted=items_upserted,
            items_deleted=items_deleted,
            cursor_after=cursor_after,
            pending_document_ids=pending_document_ids or [],
        )

    async def _fail_run(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        message: str,
        *,
        error_code: str = "sync_error",
        error_details: dict | None = None,
    ) -> SyncRunResult:
        now = datetime.now(UTC)
        run.status = ConnectorSyncRunStatus.failed.value
        run.completed_at = now
        run.error_message = message[:500]
        run.error_details_json = {"code": error_code, **(error_details or {})}
        await session.flush()
        await self._audit(
            session,
            organization_id=run.organization_id,
            user_id=None,
            action=ConnectorAuditAction.sync_failed.value,
            resource_type="connector_sync_run",
            resource_id=run.id,
            metadata={
                "sync_job_id": str(run.sync_job_id),
                "connection_id": str(run.connection_id),
                "external_source_id": str(run.external_source_id)
                if run.external_source_id
                else None,
                "error_code": error_code,
                "error_details": sanitize_metadata(error_details or {}),
                "message": message[:200],
            },
        )
        log_connector_event(
            event="connector.sync.failed",
            provider_key=getattr(getattr(run.connection, "provider", None), "key", None),
            connection_id=str(run.connection_id),
            external_source_id=(str(run.external_source_id) if run.external_source_id else None),
            sync_run_id=str(run.id),
            organization_id=str(run.organization_id),
            error_code=error_code,
            message=message[:200],
        )
        if error_code == "rate_limit":
            await self._audit(
                session,
                organization_id=run.organization_id,
                user_id=None,
                action=ConnectorAuditAction.sync_retry_scheduled.value,
                resource_type="connector_sync_run",
                resource_id=run.id,
                metadata={
                    "sync_job_id": str(run.sync_job_id),
                    "connection_id": str(run.connection_id),
                    "external_source_id": (
                        str(run.external_source_id) if run.external_source_id else None
                    ),
                    "error_code": error_code,
                    "retry_after_seconds": (error_details or {}).get("retry_after_seconds"),
                },
            )
            log_connector_event(
                event="connector.sync.retry_scheduled",
                provider_key=getattr(getattr(run.connection, "provider", None), "key", None),
                connection_id=str(run.connection_id),
                external_source_id=(
                    str(run.external_source_id) if run.external_source_id else None
                ),
                sync_run_id=str(run.id),
                organization_id=str(run.organization_id),
                retry_after_seconds=(error_details or {}).get("retry_after_seconds"),
            )
        _logger.warning(
            "connector.sync.failed",
            sync_run_id=str(run.id),
            provider_key=getattr(getattr(run.connection, "provider", None), "key", None),
            connection_id=str(run.connection_id),
            external_source_id=str(run.external_source_id) if run.external_source_id else None,
            error_code=error_code,
            error=message[:200],
        )
        return SyncRunResult(
            sync_run_id=run.id,
            status="failed",
            items_seen=run.items_seen,
            items_upserted=run.items_upserted,
            items_deleted=run.items_deleted,
            cursor_after=dict(run.cursor_before_json or {}),
            error_message=message,
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
        await self.audit_service.record(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=sanitize_metadata(metadata),
        )

    async def _cancel_run_in_flight(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        items_seen: int,
        items_upserted: int,
    ) -> SyncRunResult:
        run.completed_at = datetime.now(UTC)
        run.items_seen = items_seen
        run.items_upserted = items_upserted
        await session.flush()
        return SyncRunResult(
            sync_run_id=run.id,
            status="cancelled",
            items_seen=items_seen,
            items_upserted=items_upserted,
            items_deleted=0,
            cursor_after=dict(run.cursor_before_json or {}),
            error_message="Cancelled mid-sync",
        )

    async def _is_cancelled(self, session: AsyncSession, *, run_id: UUID) -> bool:
        result = await session.execute(
            select(ConnectorSyncRun.status).where(ConnectorSyncRun.id == run_id)
        )
        current = result.scalar_one_or_none()
        return current == ConnectorSyncRunStatus.cancelled.value

    async def _create_queued_run(
        self,
        session: AsyncSession,
        *,
        job: ConnectorSyncJob,
        trigger_type: str,
    ) -> ConnectorSyncRun:
        cursor_before = dict(job.cursor_json or {})
        sync_version = int(datetime.now(UTC).timestamp())
        run = await self.repository.create_sync_run(
            session,
            organization_id=job.organization_id,
            sync_job_id=job.id,
            connection_id=job.connection_id,
            sync_version=sync_version,
            external_source_id=job.external_source_id,
            status=ConnectorSyncRunStatus.queued.value,
            cursor_before=cursor_before,
        )
        run.trigger_type = trigger_type
        await session.flush()
        await session.refresh(run)
        return run

    async def _has_active_run(self, session: AsyncSession, *, job_id: UUID) -> bool:
        result = await session.execute(
            select(ConnectorSyncRun.id).where(
                ConnectorSyncRun.sync_job_id == job_id,
                ConnectorSyncRun.status.in_(
                    [
                        ConnectorSyncRunStatus.queued.value,
                        ConnectorSyncRunStatus.running.value,
                    ]
                ),
            )
        )
        return result.scalar_one_or_none() is not None

    async def _assert_no_active_run(self, session: AsyncSession, *, job_id: UUID) -> None:
        if await self._has_active_run(session, job_id=job_id):
            raise SyncEngineError(
                "sync is already queued or running for this job; cancel or wait for it to finish"
            )

    async def _refresh_oauth_if_needed(
        self,
        session: AsyncSession,
        *,
        connection: ConnectorConnection,
        credential: ConnectorCredential,
        organization_id: UUID,
    ) -> ConnectorCredential:
        """Proactively refresh an OAuth credential that is expired or near expiry.

        Returns the refreshed credential if refresh succeeded, otherwise the original.
        No-ops when oauth_lifecycle is not configured or credential is not OAuth.
        """
        if self._oauth_lifecycle is None:
            return credential
        if credential.auth_type != ConnectorAuthType.oauth2.value:
            return credential

        expires_at = credential.expires_at
        if expires_at is None:
            return credential

        now = datetime.now(UTC)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at > now + timedelta(seconds=60):
            return credential

        _logger.info(
            "connector.sync.proactive_token_refresh",
            connection_id=str(connection.id),
            provider_key=getattr(getattr(connection, "provider", None), "key", None),
            expires_at=expires_at.isoformat(),
        )
        try:
            await self._oauth_lifecycle.refresh_oauth_credential(
                session,
                organization_id=organization_id,
                connection_id=connection.id,
            )
            refreshed = await self.repository.get_current_credential(
                session,
                organization_id=organization_id,
                connection_id=connection.id,
            )
            if refreshed is not None:
                return refreshed
        except Exception as exc:
            _logger.warning(
                "connector.sync.proactive_token_refresh_failed",
                connection_id=str(connection.id),
                error=str(exc)[:200],
            )
        return credential

    async def _refresh_and_retry(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        job: ConnectorSyncJob,
        connection: ConnectorConnection,
        adapter: Any,
        credential: ConnectorCredential,
        organization_id: UUID,
        cursor_before: dict,
        use_incremental: bool,
    ) -> SyncRunResult | None:
        """On auth failure, refresh the OAuth token and retry the sync once.

        Returns the SyncRunResult on success, or None if this connection is not
        OAuth, no lifecycle service is configured, or the refresh/retry also fails.
        """
        if self._oauth_lifecycle is None:
            return None
        if credential.auth_type != ConnectorAuthType.oauth2.value:
            return None

        _logger.info(
            "connector.sync.auth_error_refresh_attempt",
            connection_id=str(connection.id),
            provider_key=getattr(getattr(connection, "provider", None), "key", None),
        )
        try:
            await self._oauth_lifecycle.refresh_oauth_credential(
                session,
                organization_id=organization_id,
                connection_id=connection.id,
            )
            new_credential = await self.repository.get_current_credential(
                session,
                organization_id=organization_id,
                connection_id=connection.id,
            )
            if new_credential is None:
                return None
            new_decrypted = self.credential_vault.decrypt(new_credential)
        except Exception as exc:
            _logger.warning(
                "connector.sync.auth_error_refresh_failed",
                connection_id=str(connection.id),
                error=str(exc)[:200],
            )
            return None

        _logger.info(
            "connector.sync.auth_error_retry",
            connection_id=str(connection.id),
        )
        try:
            if use_incremental:
                return await self._run_incremental_sync(
                    session,
                    run=run,
                    job=job,
                    connection=connection,
                    adapter=adapter,
                    decrypted_credential=new_decrypted,
                    cursor=cursor_before,
                )
            else:
                return await self._run_full_sync(
                    session,
                    run=run,
                    job=job,
                    connection=connection,
                    adapter=adapter,
                    decrypted_credential=new_decrypted,
                )
        except Exception as exc:
            _logger.warning(
                "connector.sync.auth_error_retry_failed",
                connection_id=str(connection.id),
                error=str(exc)[:200],
            )
            return None

    async def _mark_connection_error(
        self,
        session: AsyncSession,
        connection: ConnectorConnection,
        message: str,
    ) -> None:
        connection.status = ConnectorConnectionStatus.error.value
        connection.error_message = message[:500]
        await session.flush()

    async def _require_sync_job(
        self, session: AsyncSession, organization_id: UUID, job_id: UUID
    ) -> ConnectorSyncJob:
        job = await self.get_sync_job(session, organization_id=organization_id, job_id=job_id)
        if job is None:
            raise SyncEngineError(f"sync job {job_id} not found")
        return job

    async def _require_sync_run(
        self, session: AsyncSession, organization_id: UUID, run_id: UUID
    ) -> ConnectorSyncRun:
        run = await self.get_sync_run(session, organization_id=organization_id, run_id=run_id)
        if run is None:
            raise SyncEngineError(f"sync run {run_id} not found")
        return run
