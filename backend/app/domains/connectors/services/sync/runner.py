"""Sync run lifecycle: lease, page loop, tombstones, completion, failure (R06-11).

``run_sync`` takes a session factory (the worker: one transaction per unit of work, see
``scope.py``) or a session the caller holds (single transaction, the 0.5 behaviour). A run
that is ``running`` with a checkpoint continues from ``checkpoint_cursor`` with its
persisted counters, so a worker restart or a re-enqueue resumes instead of starting over.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger, log_connector_event
from app.core.metrics_workers import record_connector_sync_deferred
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.services.provider_adapter import (
    ConnectorAdapterNotFoundError,
    ConnectorAuthError,
    ConnectorPermissionError,
)
from app.domains.connectors.services.sync import lease
from app.domains.connectors.services.sync.common import SyncRunResult, source_id_str
from app.domains.connectors.services.sync.context import LoopState, RunContext
from app.domains.connectors.services.sync.fetcher import RateLimitDeferred, provider_source_id
from app.domains.connectors.services.sync.pages import SyncPager, is_cancelled_now, load_run
from app.domains.connectors.services.sync.scope import SessionFactory, SyncScope, make_scope
from app.models.connector import ConnectorConnection
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import (
    ConnectorAuthType,
    ConnectorConnectionStatus,
    ConnectorCredentialStatus,
    ConnectorSyncRunStatus,
)

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine

_logger = get_logger("connectors.sync_engine")
_FINISHED = (ConnectorSyncRunStatus.completed.value, ConnectorSyncRunStatus.failed.value)


def _result(
    ctx: RunContext,
    status: str,
    *,
    error_message: str | None = None,
    requeue_after_seconds: int | None = None,
) -> SyncRunResult:
    state = ctx.state
    return SyncRunResult(
        sync_run_id=ctx.run_id,
        status=status,
        items_seen=state.items_seen,
        items_upserted=state.items_upserted,
        items_deleted=state.items_deleted,
        cursor_after={},
        error_message=error_message,
        requeue_after_seconds=requeue_after_seconds,
        pages_committed=state.pages_committed,
    )


def _run_result(
    run: ConnectorSyncRun,
    status: str,
    *,
    error_message: str | None = None,
    requeue_after_seconds: int | None = None,
) -> SyncRunResult:
    return SyncRunResult(
        sync_run_id=run.id,
        status=status,
        items_seen=run.items_seen or 0,
        items_upserted=run.items_upserted or 0,
        items_deleted=run.items_deleted or 0,
        cursor_after=dict(run.cursor_after_json or {}),
        error_message=error_message,
        requeue_after_seconds=requeue_after_seconds,
        pages_committed=run.pages_committed or 0,
    )


class SyncRunner:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine
        self.pager = SyncPager(engine)

    async def run_sync(
        self,
        session_or_factory: AsyncSession | SessionFactory,
        *,
        sync_run_id: UUID,
        organization_id: UUID,
        lease_owner: str | None = None,
    ) -> SyncRunResult:
        scope = make_scope(session_or_factory)
        owner = lease_owner or f"inline:{uuid4().hex}"
        async with scope.transaction() as session:
            started = await self._start(session, sync_run_id, organization_id, owner)
        if isinstance(started, SyncRunResult):
            return started
        try:
            return await self._execute(scope, started)
        except lease.LeaseLostError:
            record_connector_sync_deferred("lease_lost")
            _logger.warning(
                "connector.sync.lease_lost",
                sync_run_id=str(sync_run_id),
                organization_id=str(organization_id),
            )
            return _result(started, "lease_lost", error_message="lease taken by another worker")

    # -- start ----------------------------------------------------------------------

    async def _start(
        self, session: AsyncSession, run_id: UUID, organization_id: UUID, owner: str
    ) -> RunContext | SyncRunResult:
        """Lease the run and resolve the job, connection, credential, and adapter."""
        engine = self.engine
        run = await engine._require_sync_run(session, organization_id, run_id)
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
        if run.status in _FINISHED:
            return _run_result(run, run.status, error_message="run already finished")
        now = datetime.now(UTC)
        cap = await lease.over_cap(session, run, now)
        if cap is not None:
            record_connector_sync_deferred(cap)
            _logger.info("connector.sync.cap_deferred", sync_run_id=str(run.id), reason=cap)
            return _run_result(
                run,
                run.status,
                error_message=f"deferred: {cap}",
                requeue_after_seconds=settings.connector_sync_cap_retry_seconds,
            )
        was_queued = run.status == ConnectorSyncRunStatus.queued.value
        if not await lease.try_lease(session, run_id=run.id, owner=owner, now=now):
            record_connector_sync_deferred("lease_held")
            return _run_result(run, run.status, error_message="run is leased by another worker")
        await session.refresh(run)
        if was_queued:
            await engine._audit(
                session,
                organization_id=organization_id,
                user_id=None,
                action=ConnectorAuditAction.sync_started.value,
                resource_type="connector_sync_run",
                resource_id=run.id,
                metadata={
                    "sync_job_id": str(run.sync_job_id),
                    "connection_id": str(run.connection_id),
                    "external_source_id": source_id_str(run),
                    "trigger_type": run.trigger_type,
                },
            )
        return await self._resolve(session, run, owner, resumed=not was_queued)

    async def _resolve(
        self, session: AsyncSession, run: ConnectorSyncRun, owner: str, *, resumed: bool
    ) -> RunContext | SyncRunResult:
        engine = self.engine
        organization_id = run.organization_id
        job = await self._load_job(session, run)
        if job is None:
            return await engine._fail_run(session, run, "sync job not found")
        connection = job.connection
        if connection.status != ConnectorConnectionStatus.active.value:
            return await engine._fail_run(
                session,
                run,
                f"connection is not active (status={connection.status})",
                error_code="connection_not_active",
            )
        has_credential = connection.provider.auth_type != ConnectorAuthType.none.value
        decrypted: dict = {}
        if has_credential:
            credential = await engine.repository.get_current_credential(
                session, organization_id=organization_id, connection_id=connection.id
            )
            if credential is None:
                return await engine._fail_run(session, run, "no credential found for connection")
            if credential.status == ConnectorCredentialStatus.revoked.value:
                return await engine._fail_run(session, run, "credential has been revoked")
            credential = await engine._refresh_oauth_if_needed(
                session,
                connection=connection,
                credential=credential,
                organization_id=organization_id,
            )
            try:
                decrypted = engine.credential_vault.decrypt(credential)
            except Exception as exc:
                return await engine._fail_run(session, run, f"credential decryption failed: {exc}")
        try:
            adapter = engine.adapter_registry.require(connection.provider.key)
        except ConnectorAdapterNotFoundError as exc:
            return await engine._fail_run(session, run, str(exc), error_code="adapter_not_found")

        cursor_before = dict(run.cursor_before_json or {})
        incremental = bool(cursor_before) and hasattr(adapter, "delta_sync")
        state = LoopState.from_run(run, start_cursor=cursor_before if incremental else {})
        if resumed:
            _logger.info(
                "connector.sync.resumed",
                sync_run_id=str(run.id),
                organization_id=str(organization_id),
                pages_committed=state.pages_committed,
                from_checkpoint=state.resumed,
            )
        return RunContext(
            run_id=run.id,
            organization_id=organization_id,
            connection_id=run.connection_id,
            sync_job_id=run.sync_job_id,
            owner=owner,
            adapter=adapter,
            decrypted=decrypted,
            provider_key=connection.provider.key,
            provider_source_id=provider_source_id(job),
            external_source_id=run.external_source_id,
            incremental=incremental,
            has_credential=has_credential,
            state=state,
        )

    async def _load_job(self, session: AsyncSession, run: ConnectorSyncRun) -> Any:
        job_result = await session.execute(
            select(ConnectorSyncJob)
            .options(
                selectinload(ConnectorSyncJob.connection).selectinload(
                    ConnectorConnection.provider
                ),
                selectinload(ConnectorSyncJob.external_source),
            )
            .where(ConnectorSyncJob.id == run.sync_job_id)
        )
        return job_result.scalar_one_or_none()

    # -- execution --------------------------------------------------------------------

    async def _execute(self, scope: SyncScope, ctx: RunContext) -> SyncRunResult:
        try:
            if not await self.pager.run_pages(scope, ctx):
                return await self._cancelled(scope, ctx)
            if not ctx.incremental and not await self._tombstone_unseen(scope, ctx):
                return await self._cancelled(scope, ctx)
            return await self._complete(scope, ctx)
        except lease.LeaseLostError:
            raise
        except RateLimitDeferred as deferred:
            return await self._defer(scope, ctx, deferred.retry_after_seconds)
        except ConnectorAuthError as exc:
            return await self._fail(scope, ctx, str(exc), "auth_error", mark_connection=True)
        except ConnectorPermissionError as exc:
            return await self._fail(
                scope,
                ctx,
                "permission denied",
                "permission_denied",
                details={"reason": exc.__class__.__name__},
            )
        except Exception as exc:
            return await self._fail(scope, ctx, str(exc), "sync_error")

    async def _tombstone_unseen(self, scope: SyncScope, ctx: RunContext) -> bool:
        """Tombstone, in batches, live items this full sync never marked seen."""
        batch = settings.connector_sync_tombstone_batch_size
        while True:
            if await is_cancelled_now(scope, ctx):
                return False
            async with scope.transaction() as session:
                run = await load_run(session, ctx)
                count = await self.engine.differ.tombstone_unseen_batch(
                    session, run=run, limit=batch
                )
                deleted = ctx.state.items_deleted + count
                await lease.owned_update(
                    session,
                    run_id=ctx.run_id,
                    owner=ctx.owner,
                    values={"items_deleted": deleted, "heartbeat_at": datetime.now(UTC)},
                )
            ctx.state.items_deleted = deleted
            if count < batch:
                return True

    async def _complete(self, scope: SyncScope, ctx: RunContext) -> SyncRunResult:
        engine = self.engine
        state = ctx.state
        async with scope.transaction() as session:
            run = await load_run(session, ctx)
            if run.status == ConnectorSyncRunStatus.cancelled.value:
                return _result(ctx, "cancelled", error_message="Cancelled mid-sync")
            if run.lease_owner != ctx.owner:
                raise lease.LeaseLostError(str(ctx.run_id))
            result = await engine._complete_run(
                session,
                run,
                items_seen=state.items_seen,
                items_upserted=state.items_upserted,
                items_deleted=state.items_deleted,
                cursor_after=state.cursor_after,
            )
            job = await session.get(ConnectorSyncJob, run.sync_job_id)
            await self._record_success(session, run=run, job=job, result=result)
        return result

    async def _record_success(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        job: ConnectorSyncJob | None,
        result: SyncRunResult,
    ) -> None:
        now = datetime.now(UTC)
        connection = run.connection
        if job is not None:
            job.last_run_at = now
            job.cursor_json = result.cursor_after
            job.error_message = None
        connection.last_sync_at = now
        await session.flush()
        await self.engine._audit(
            session,
            organization_id=run.organization_id,
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
        fields: dict[str, Any] = {
            "provider_key": getattr(getattr(connection, "provider", None), "key", None),
            "connection_id": str(connection.id),
            "external_source_id": source_id_str(run),
            "sync_run_id": str(run.id),
            "organization_id": str(run.organization_id),
            "items_seen": result.items_seen,
            "items_upserted": result.items_upserted,
            "items_deleted": result.items_deleted,
        }
        log_connector_event(event="connector.sync.completed", **fields)
        _logger.info("connector.sync.completed", pages_committed=result.pages_committed, **fields)

    async def _cancelled(self, scope: SyncScope, ctx: RunContext) -> SyncRunResult:
        """Stop a cancelled run: the committed pages and checkpoint stay, the lease is freed."""
        async with scope.transaction() as session:
            await session.execute(
                update(ConnectorSyncRun)
                .where(ConnectorSyncRun.id == ctx.run_id, ConnectorSyncRun.lease_owner == ctx.owner)
                .values(lease_owner=None, heartbeat_at=datetime.now(UTC))
                .execution_options(synchronize_session=False)
            )
        _logger.info(
            "connector.sync.cancelled",
            sync_run_id=str(ctx.run_id),
            organization_id=str(ctx.organization_id),
            pages_committed=ctx.state.pages_committed,
            items_seen=ctx.state.items_seen,
        )
        return _result(ctx, "cancelled", error_message="Cancelled mid-sync")

    async def _defer(self, scope: SyncScope, ctx: RunContext, retry_after: int) -> SyncRunResult:
        """Long ``Retry-After``: keep the checkpoint, free the lease, re-enqueue later.

        The heartbeat is set to the resume time so the stale-run sweep leaves the run
        alone while it waits; the re-enqueued task leases it (no owner) and resumes.
        """
        async with scope.transaction() as session:
            run = await load_run(session, ctx)
            cancelled = run.status == ConnectorSyncRunStatus.cancelled.value
            if not cancelled:
                await self._release_for_retry(session, ctx, run, retry_after)
        if cancelled:
            return await self._cancelled(scope, ctx)
        record_connector_sync_deferred("rate_limit")
        log_connector_event(
            event="connector.sync.retry_scheduled",
            provider_key=ctx.provider_key,
            connection_id=str(ctx.connection_id),
            external_source_id=str(ctx.external_source_id) if ctx.external_source_id else None,
            sync_run_id=str(ctx.run_id),
            organization_id=str(ctx.organization_id),
            retry_after_seconds=retry_after,
        )
        return _result(
            ctx,
            ConnectorSyncRunStatus.running.value,
            error_message="rate limited; re-enqueued",
            requeue_after_seconds=retry_after,
        )

    async def _release_for_retry(
        self, session: AsyncSession, ctx: RunContext, run: ConnectorSyncRun, retry_after: int
    ) -> None:
        resume_at = datetime.now(UTC) + timedelta(seconds=retry_after)
        await lease.owned_update(
            session,
            run_id=ctx.run_id,
            owner=ctx.owner,
            values={"lease_owner": None, "heartbeat_at": resume_at},
        )
        await self.engine._audit(
            session,
            organization_id=ctx.organization_id,
            user_id=None,
            action=ConnectorAuditAction.sync_retry_scheduled.value,
            resource_type="connector_sync_run",
            resource_id=ctx.run_id,
            metadata={
                "sync_job_id": str(ctx.sync_job_id),
                "connection_id": str(ctx.connection_id),
                "external_source_id": source_id_str(run),
                "error_code": "rate_limit",
                "retry_after_seconds": retry_after,
            },
        )

    async def _fail(
        self,
        scope: SyncScope,
        ctx: RunContext,
        message: str,
        code: str,
        *,
        details: dict | None = None,
        mark_connection: bool = False,
    ) -> SyncRunResult:
        engine = self.engine
        async with scope.transaction() as session:
            run = await load_run(session, ctx)
            if run.status == ConnectorSyncRunStatus.cancelled.value:
                return _result(ctx, "cancelled", error_message="Cancelled mid-sync")
            if mark_connection:
                await engine._mark_connection_error(session, run.connection, message)
            return await engine._fail_run(
                session, run, message, error_code=code, error_details=details
            )
