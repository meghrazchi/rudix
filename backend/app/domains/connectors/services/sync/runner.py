"""Sync run execution: run lifecycle and the full / incremental page loops (R06-11 split)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger, log_connector_event
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.services.provider_adapter import (
    ConnectorAdapterNotFoundError,
    ConnectorAuthError,
    ConnectorContentError,
    ConnectorPermissionError,
    ConnectorRateLimitError,
)
from app.domains.connectors.services.sync.common import SyncRunResult, source_id_str
from app.models.connector import ConnectorConnection
from app.models.connector_credential import ConnectorCredential
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


class SyncRunner:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    async def run_sync(
        self, session: AsyncSession, *, sync_run_id: UUID, organization_id: UUID
    ) -> SyncRunResult:
        """Execute a single sync run through its complete lifecycle."""
        engine = self.engine
        run = await engine._require_sync_run(session, organization_id, sync_run_id)
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

        run.status = ConnectorSyncRunStatus.running.value
        run.started_at = datetime.now(UTC)
        await session.flush()
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

        credential: ConnectorCredential | None = None
        if connection.provider.auth_type == ConnectorAuthType.none.value:
            decrypted: dict = {}
        else:
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
        use_incremental = bool(cursor_before) and hasattr(adapter, "delta_sync")
        try:
            result = await self._run_loop(
                session,
                run=run,
                job=job,
                connection=connection,
                adapter=adapter,
                decrypted=decrypted,
                cursor_before=cursor_before,
                use_incremental=use_incremental,
            )
        except ConnectorAuthError as exc:
            # For OAuth connections: attempt a token refresh + one retry before giving up.
            retry_result = None
            if credential is not None:
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
            if retry_result is None:
                await engine._mark_connection_error(session, connection, str(exc))
                return await engine._fail_run(session, run, str(exc), error_code="auth_error")
            result = retry_result
        except ConnectorRateLimitError as exc:
            return await engine._fail_run(
                session,
                run,
                str(exc),
                error_code="rate_limit",
                error_details={"retry_after_seconds": exc.retry_after_seconds},
            )
        except ConnectorPermissionError as exc:
            return await engine._fail_run(
                session,
                run,
                "permission denied",
                error_code="permission_denied",
                error_details={"reason": exc.__class__.__name__},
            )
        except Exception as exc:
            return await engine._fail_run(session, run, str(exc))

        await self._record_success(session, run=run, job=job, connection=connection, result=result)
        return result

    async def _load_job(self, session: AsyncSession, run: ConnectorSyncRun) -> Any:
        job_result = await session.execute(
            select(ConnectorSyncJob)
            .options(
                selectinload(ConnectorSyncJob.connection).selectinload(ConnectorConnection.provider)
            )
            .where(ConnectorSyncJob.id == run.sync_job_id)
        )
        return job_result.scalar_one_or_none()

    async def _record_success(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        job: ConnectorSyncJob,
        connection: ConnectorConnection,
        result: SyncRunResult,
    ) -> None:
        now = datetime.now(UTC)
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
        provider_key = getattr(getattr(connection, "provider", None), "key", None)
        fields: dict[str, Any] = {
            "provider_key": provider_key,
            "connection_id": str(connection.id),
            "external_source_id": source_id_str(run),
            "sync_run_id": str(run.id),
            "organization_id": str(run.organization_id),
            "items_seen": result.items_seen,
            "items_upserted": result.items_upserted,
            "items_deleted": result.items_deleted,
        }
        log_connector_event(event="connector.sync.completed", **fields)
        _logger.info("connector.sync.completed", **fields)

    async def _run_loop(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        job: ConnectorSyncJob,
        connection: ConnectorConnection,
        adapter: Any,
        decrypted: dict,
        cursor_before: dict,
        use_incremental: bool,
    ) -> SyncRunResult:
        if use_incremental:
            return await self.run_incremental_sync(
                session,
                run=run,
                job=job,
                connection=connection,
                adapter=adapter,
                decrypted_credential=decrypted,
                cursor=cursor_before,
            )
        return await self.run_full_sync(
            session,
            run=run,
            job=job,
            connection=connection,
            adapter=adapter,
            decrypted_credential=decrypted,
        )

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
        new_decrypted = await self.engine.fetcher.refreshed_credential(
            session, connection=connection, credential=credential, organization_id=organization_id
        )
        if new_decrypted is None:
            return None
        try:
            return await self._run_loop(
                session,
                run=run,
                job=job,
                connection=connection,
                adapter=adapter,
                decrypted=new_decrypted,
                cursor_before=cursor_before,
                use_incremental=use_incremental,
            )
        except Exception as exc:
            _logger.warning(
                "connector.sync.auth_error_retry_failed",
                connection_id=str(connection.id),
                error=str(exc)[:200],
            )
            return None

    async def run_full_sync(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        job: ConnectorSyncJob,
        connection: ConnectorConnection,
        adapter: Any,
        decrypted_credential: dict,
    ) -> SyncRunResult:
        engine = self.engine
        items_seen = 0
        items_upserted = 0
        cursor: dict = {}
        seen_provider_ids: set[str] = set()
        pending_document_ids: list[tuple[str, str]] = []

        while True:
            if await engine._is_cancelled(session, run_id=run.id):
                return await engine._cancel_run_in_flight(session, run, items_seen, items_upserted)
            page = await engine.fetcher.fetch_page(
                adapter=adapter,
                run=run,
                job=job,
                decrypted_credential=decrypted_credential,
                cursor=cursor,
                incremental=False,
            )
            for norm_item in page.items:
                items_seen += 1
                seen_provider_ids.add(norm_item.provider_item_id)
                if await engine._upsert_item_if_changed(session, run, norm_item):
                    items_upserted += 1
                    pending = await engine._maybe_ingest_file_item(
                        session,
                        run=run,
                        connection=connection,
                        adapter=adapter,
                        norm_item=norm_item,
                        decrypted_credential=decrypted_credential,
                    )
                    if pending is not None:
                        pending_document_ids.append(pending)
            await engine._flush_run_progress(
                session, run, items_seen=items_seen, items_upserted=items_upserted
            )
            if not page.has_more or page.next_cursor is None:
                break
            cursor = page.next_cursor

        items_deleted = await engine._tombstone_unseen_items(
            session, run=run, seen_provider_ids=seen_provider_ids
        )
        return await engine._complete_run(
            session,
            run,
            items_seen=items_seen,
            items_upserted=items_upserted,
            items_deleted=items_deleted,
            cursor_after=cursor,
            pending_document_ids=pending_document_ids,
        )

    async def run_incremental_sync(
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
        engine = self.engine
        items_seen = 0
        items_upserted = 0
        items_deleted = 0
        pending_document_ids: list[tuple[str, str]] = []

        while True:
            if await engine._is_cancelled(session, run_id=run.id):
                return await engine._cancel_run_in_flight(session, run, items_seen, items_upserted)
            page = await engine.fetcher.fetch_page(
                adapter=adapter,
                run=run,
                job=job,
                decrypted_credential=decrypted_credential,
                cursor=cursor,
                incremental=True,
            )
            for delta_item in page.items:
                items_seen += 1
                if delta_item.is_deleted or delta_item.permission_revoked:
                    if await engine._tombstone_item(session, run, delta_item):
                        items_deleted += 1
                elif delta_item.item is not None:
                    try:
                        if await engine._upsert_item_if_changed(session, run, delta_item.item):
                            items_upserted += 1
                            pending = await engine._maybe_ingest_file_item(
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
                        await self.record_content_skip(session, run, delta_item.item)
            await engine._flush_run_progress(
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

        return await engine._complete_run(
            session,
            run,
            items_seen=items_seen,
            items_upserted=items_upserted,
            items_deleted=items_deleted,
            cursor_after=cursor,
            pending_document_ids=pending_document_ids,
        )

    async def record_content_skip(
        self, session: AsyncSession, run: ConnectorSyncRun, item: Any
    ) -> None:
        await self.engine._audit(
            session,
            organization_id=run.organization_id,
            user_id=None,
            action=ConnectorAuditAction.sync_item_skipped.value,
            resource_type="external_item",
            resource_id=None,
            metadata={
                "sync_run_id": str(run.id),
                "connection_id": str(run.connection_id),
                "external_source_id": source_id_str(run),
                "provider_key": item.provider_key,
                "provider_item_id": item.provider_item_id,
                "reason": "content_error",
            },
        )
        log_connector_event(
            event="connector.sync.item.skipped",
            provider_key=item.provider_key,
            connection_id=str(run.connection_id),
            external_source_id=source_id_str(run),
            external_item_id=None,
            sync_run_id=str(run.id),
            organization_id=str(run.organization_id),
            reason="content_error",
        )
