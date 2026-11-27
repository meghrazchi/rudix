"""Sync writes: file ingestion through the bridge, run progress and outcomes, audit (R06-11)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, log_connector_event
from app.domains.admin.services.audit_service import sanitize_metadata
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.services.sync.common import (
    FILE_ITEM_TYPES,
    SyncRunResult,
    source_id_str,
)
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.connector_sync import ConnectorSyncRun
from app.models.enums import ConnectorConnectionStatus, ConnectorSyncRunStatus, DocumentStatus

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine

_logger = get_logger("connectors.sync_engine")


def _provider_key(run: ConnectorSyncRun) -> str | None:
    return getattr(getattr(run.connection, "provider", None), "key", None)


class SyncWriter:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    # -- file ingestion -------------------------------------------------------

    async def _item_outcome(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        norm_item: Any,
        ext_item: ExternalItem | None,
        action: str,
        reason: str,
        event: str,
        error: str | None = None,
        connection_id: UUID | None = None,
    ) -> None:
        """Audit and log a skipped or failed file ingestion (no document text)."""
        metadata: dict[str, object] = {
            "sync_run_id": str(run.id),
            "connection_id": str(run.connection_id),
            "external_source_id": source_id_str(run),
            "provider_key": norm_item.provider_key,
            "provider_item_id": norm_item.provider_item_id,
            "reason": reason,
        }
        log_fields: dict[str, Any] = {"reason": reason}
        if error is not None:
            metadata["error"] = error
            log_fields = {"error": error}
        await self.engine._audit(
            session,
            organization_id=run.organization_id,
            user_id=None,
            action=action,
            resource_type="external_item",
            resource_id=ext_item.id if ext_item is not None else None,
            metadata=metadata,
        )
        log_connector_event(
            event=event,
            provider_key=norm_item.provider_key,
            connection_id=str(connection_id or run.connection_id),
            external_source_id=source_id_str(run),
            external_item_id=str(ext_item.id) if ext_item is not None else None,
            sync_run_id=str(run.id),
            organization_id=str(run.organization_id),
            **log_fields,
        )

    async def maybe_ingest_file_item(
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
        bridge = self.engine.ingestion_bridge
        if bridge is None or norm_item.item_type not in FILE_ITEM_TYPES:
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
            await self._item_outcome(
                session,
                run=run,
                norm_item=norm_item,
                ext_item=ext_item,
                action=ConnectorAuditAction.ingestion_failed.value,
                reason="download_failed",
                event="connector.ingestion.download_failed",
                error=exc.__class__.__name__,
            )
            _logger.warning(
                "connector.ingestion.download_failed",
                provider_item_id=norm_item.provider_item_id,
                error=str(exc)[:200],
            )
            return None

        if download is None:
            await self._item_outcome(
                session,
                run=run,
                norm_item=norm_item,
                ext_item=ext_item,
                action=ConnectorAuditAction.ingestion_skipped.value,
                reason="download_not_available",
                event="connector.ingestion.skipped",
            )
            return None

        content, provider_filename, resolved_mime = download
        # Use the human-readable source title as the filename, keeping the
        # extension that came back from the download (handles Google-native export).
        ext = os.path.splitext(provider_filename)[1]
        title = (norm_item.title or "").strip()
        filename = title if title.lower().endswith(ext.lower()) else f"{title}{ext}"

        uploader_user_id = connection.created_by_user_id
        if uploader_user_id is None:
            await self._item_outcome(
                session,
                run=run,
                norm_item=norm_item,
                ext_item=ext_item,
                action=ConnectorAuditAction.ingestion_skipped.value,
                reason="missing_uploader_user",
                event="connector.ingestion.skipped",
                connection_id=connection.id,
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
            result = await bridge.ingest_item(
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
                metadata=_provenance_metadata(norm_item, connection),
                sync_version=run.sync_version,
            )
            _logger.info(
                "connector.ingestion.result",
                provider_item_id=norm_item.provider_item_id,
                document_id=str(result.document_id) if result.document_id else None,
                status=result.status,
            )
            if result.status == DocumentStatus.pending_scan and result.document_id is not None:
                return (str(result.document_id), str(uploader_user_id))
            return None
        except Exception as exc:
            await self._item_outcome(
                session,
                run=run,
                norm_item=norm_item,
                ext_item=ext_item,
                action=ConnectorAuditAction.ingestion_failed.value,
                reason="bridge_error",
                event="connector.ingestion.bridge_error",
                error=exc.__class__.__name__,
            )
            _logger.error(
                "connector.ingestion.bridge_error",
                provider_item_id=norm_item.provider_item_id,
                error=str(exc)[:300],
            )
        return None

    # -- run progress and outcomes ---------------------------------------------

    async def flush_run_progress(
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

    async def complete_run(
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
        run.status = ConnectorSyncRunStatus.completed.value
        run.completed_at = datetime.now(UTC)
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

    async def fail_run(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        message: str,
        *,
        error_code: str = "sync_error",
        error_details: dict | None = None,
    ) -> SyncRunResult:
        run.status = ConnectorSyncRunStatus.failed.value
        run.completed_at = datetime.now(UTC)
        run.error_message = message[:500]
        run.error_details_json = {"code": error_code, **(error_details or {})}
        await session.flush()
        common: dict[str, object] = {
            "sync_job_id": str(run.sync_job_id),
            "connection_id": str(run.connection_id),
            "external_source_id": source_id_str(run),
            "error_code": error_code,
        }
        await self.engine._audit(
            session,
            organization_id=run.organization_id,
            user_id=None,
            action=ConnectorAuditAction.sync_failed.value,
            resource_type="connector_sync_run",
            resource_id=run.id,
            metadata={
                **common,
                "error_details": sanitize_metadata(error_details or {}),
                "message": message[:200],
            },
        )
        log_connector_event(
            event="connector.sync.failed",
            provider_key=_provider_key(run),
            connection_id=str(run.connection_id),
            external_source_id=source_id_str(run),
            sync_run_id=str(run.id),
            organization_id=str(run.organization_id),
            error_code=error_code,
            message=message[:200],
        )
        if error_code == "rate_limit":
            retry_after = (error_details or {}).get("retry_after_seconds")
            await self.engine._audit(
                session,
                organization_id=run.organization_id,
                user_id=None,
                action=ConnectorAuditAction.sync_retry_scheduled.value,
                resource_type="connector_sync_run",
                resource_id=run.id,
                metadata={**common, "retry_after_seconds": retry_after},
            )
            log_connector_event(
                event="connector.sync.retry_scheduled",
                provider_key=_provider_key(run),
                connection_id=str(run.connection_id),
                external_source_id=source_id_str(run),
                sync_run_id=str(run.id),
                organization_id=str(run.organization_id),
                retry_after_seconds=retry_after,
            )
        _logger.warning(
            "connector.sync.failed",
            sync_run_id=str(run.id),
            provider_key=_provider_key(run),
            connection_id=str(run.connection_id),
            external_source_id=source_id_str(run),
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

    async def cancel_run_in_flight(
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

    async def is_cancelled(self, session: AsyncSession, *, run_id: UUID) -> bool:
        result = await session.execute(
            select(ConnectorSyncRun.status).where(ConnectorSyncRun.id == run_id)
        )
        return result.scalar_one_or_none() == ConnectorSyncRunStatus.cancelled.value

    async def mark_connection_error(
        self, session: AsyncSession, connection: ConnectorConnection, message: str
    ) -> None:
        connection.status = ConnectorConnectionStatus.error.value
        connection.error_message = message[:500]
        await session.flush()

    async def audit(
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
        await self.engine.audit_service.record(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=sanitize_metadata(metadata),
        )


def _provenance_metadata(norm_item: Any, connection: ConnectorConnection) -> dict[str, Any]:
    return {
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
