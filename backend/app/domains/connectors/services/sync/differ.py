"""Item diffing: change detection, ACL/rename/move conflicts, tombstones (R06-11 split)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_connector_event
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.services.provider_adapter import DeltaItem
from app.domains.connectors.services.sync.common import source_id_str
from app.models.connector import ExternalItem
from app.models.connector_source import SourceDocument
from app.models.connector_sync import ConnectorSyncRun
from app.models.enums import SyncConflictType

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine


class SyncDiffer:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    async def upsert_item_if_changed(
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
            await self.detect_unchanged_item_conflicts(session, run, existing, norm_item)
            await session.flush()
            # Treat as changed if no SourceDocument exists yet (e.g. prior sync had no bridge).
            orphaned_result = await session.execute(
                select(SourceDocument)
                .where(SourceDocument.external_item_id == existing.id)
                .limit(1)
            )
            return orphaned_result.scalar_one_or_none() is None

        await self.engine.repository.upsert_external_item(session, item=norm_item_with_version)
        return True

    async def detect_unchanged_item_conflicts(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        existing: ExternalItem,
        norm_item: Any,
    ) -> None:
        """Record ACL drift, moves, and renames of an item whose content is unchanged."""
        new_acl = getattr(norm_item, "acl_hash", None)
        if new_acl and existing.acl_hash and new_acl != existing.acl_hash:
            await self.record_conflict(
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

        new_parent = getattr(norm_item, "provider_parent_id", None)
        if existing.provider_parent_id and new_parent and new_parent != existing.provider_parent_id:
            await self.record_conflict(
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
            await self.record_conflict(
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

    async def tombstone_unseen_items(
        self, session: AsyncSession, *, run: ConnectorSyncRun, seen_provider_ids: set[str]
    ) -> int:
        result = await session.execute(
            select(ExternalItem).where(
                ExternalItem.organization_id == run.organization_id,
                ExternalItem.connection_id == run.connection_id,
                ExternalItem.deleted_at.is_(None),
                ExternalItem.sync_version <= run.sync_version,
            )
        )
        count = 0
        now = datetime.now(UTC)
        for item in result.scalars().all():
            if item.provider_item_id in seen_provider_ids:
                continue
            await self.tombstone_external_item(
                session, run=run, item=item, now=now, reason="not_seen_in_full_sync"
            )
            count += 1
        return count

    async def tombstone_external_item(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        item: ExternalItem,
        now: datetime,
        reason: str,
    ) -> None:
        item.deleted_at = now
        await self.engine.repository.record_tombstone(
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
            reason=reason,
        )
        await self.engine._audit(
            session,
            organization_id=run.organization_id,
            user_id=None,
            action=ConnectorAuditAction.source_deleted.value,
            resource_type="external_item",
            resource_id=item.id,
            metadata={
                "connection_id": str(run.connection_id),
                "external_source_id": source_id_str(run),
                "provider_item_id": item.provider_item_id,
                "reason": reason,
            },
        )

    async def tombstone_item(
        self, session: AsyncSession, run: ConnectorSyncRun, delta_item: DeltaItem
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

        reason = "permission_revoked" if delta_item.permission_revoked else "provider_deleted"
        # Permission revocations are recorded as open conflicts — the document
        # still exists remotely but is no longer accessible to this connection.
        # We tombstone the item AND create a conflict so an admin can act.
        if delta_item.permission_revoked:
            await self.record_conflict(
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
        await self.tombstone_external_item(
            session, run=run, item=item, now=datetime.now(UTC), reason=reason
        )
        return True

    async def record_conflict(
        self,
        session: AsyncSession,
        *,
        run: ConnectorSyncRun,
        external_item: ExternalItem,
        conflict_type: str,
        detail: dict,
    ) -> None:
        conflict = await self.engine.repository.record_conflict(
            session,
            organization_id=run.organization_id,
            connection_id=run.connection_id,
            provider_item_id=external_item.provider_item_id,
            conflict_type=conflict_type,
            sync_run_id=run.id,
            external_item_id=external_item.id,
            conflict_detail=detail,
        )
        await self.engine._audit(
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
            external_source_id=source_id_str(run),
            external_item_id=str(external_item.id),
            sync_run_id=str(run.id),
            organization_id=str(run.organization_id),
            conflict_type=conflict_type,
        )
