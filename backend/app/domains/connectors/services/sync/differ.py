"""Item diffing: change detection, ACL/rename/move conflicts, tombstones (R06-11 split)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_connector_event
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.repositories.connectors import (
    apply_external_item_fields,
    new_external_item,
)
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

    async def apply_full_chunk(
        self,
        session: AsyncSession,
        run: ConnectorSyncRun,
        items: list[Any],
        known: dict[str, ExternalItem],
    ) -> list[tuple[Any, bool]]:
        """Diff a slice of a full-sync page with one lookup and one flush.

        Same rules as ``upsert_item_if_changed``: an item is changed when it is new, its
        content hash differs, or it has no ``SourceDocument`` yet; unchanged items are
        checked for ACL, move, and rename conflicts. ``known`` caches the page's rows.
        """
        missing = [item.provider_item_id for item in items if item.provider_item_id not in known]
        if missing:
            rows = await session.execute(
                select(ExternalItem).where(
                    ExternalItem.organization_id == run.organization_id,
                    ExternalItem.connection_id == run.connection_id,
                    ExternalItem.provider_item_id.in_(missing),
                )
            )
            known.update({row.provider_item_id: row for row in rows.scalars().all()})
        changed: dict[str, bool] = {}
        unchanged: dict[str, ExternalItem] = {}
        for item in items:
            versioned = item.model_copy(update={"sync_version": run.sync_version})
            existing = known.get(item.provider_item_id)
            if existing is None:
                known[item.provider_item_id] = new_row = new_external_item(versioned)
                session.add(new_row)
                changed[item.provider_item_id] = True
            elif existing.content_hash == item.content_hash:
                await self.detect_unchanged_item_conflicts(session, run, existing, item)
                unchanged[item.provider_item_id] = existing
            else:
                apply_external_item_fields(existing, versioned)
                changed[item.provider_item_id] = True
        await session.flush()
        if unchanged:
            linked = await session.execute(
                select(SourceDocument.external_item_id)
                .where(SourceDocument.external_item_id.in_([r.id for r in unchanged.values()]))
                .distinct()
            )
            linked_ids = set(linked.scalars().all())
            for provider_item_id, row in unchanged.items():
                changed[provider_item_id] = row.id not in linked_ids
        return [(item, changed[item.provider_item_id]) for item in items]

    async def mark_seen(
        self, session: AsyncSession, run: ConnectorSyncRun, provider_item_ids: list[str]
    ) -> None:
        """One UPDATE per page: every item the page returned was seen by this run."""
        if not provider_item_ids:
            return
        await session.execute(
            update(ExternalItem)
            .where(
                ExternalItem.organization_id == run.organization_id,
                ExternalItem.connection_id == run.connection_id,
                ExternalItem.provider_item_id.in_(provider_item_ids),
            )
            .values(last_seen_sync_run_id=run.id, sync_version=run.sync_version)
            .execution_options(synchronize_session=False)
        )

    async def tombstone_unseen_batch(
        self, session: AsyncSession, *, run: ConnectorSyncRun, limit: int
    ) -> int:
        """Tombstone up to ``limit`` live items this full sync did not see.

        Seen means ``last_seen_sync_run_id = run.id`` (persisted per page, so a resumed run
        keeps what earlier attempts saw); items written by a newer run are left alone.
        """
        result = await session.execute(
            select(ExternalItem)
            .where(
                ExternalItem.organization_id == run.organization_id,
                ExternalItem.connection_id == run.connection_id,
                ExternalItem.deleted_at.is_(None),
                ExternalItem.sync_version <= run.sync_version,
                ExternalItem.last_seen_sync_run_id.is_distinct_from(run.id),
            )
            .order_by(ExternalItem.id)
            .limit(limit)
        )
        items = list(result.scalars().all())
        now = datetime.now(UTC)
        for item in items:
            await self.tombstone_external_item(
                session, run=run, item=item, now=now, reason="not_seen_in_full_sync"
            )
        await session.flush()
        return len(items)

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
