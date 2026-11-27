"""The page loop of a sync run: one provider call, then one transaction per page (R06-11).

Per page: the provider call runs with no transaction open; then one transaction writes the
items, marks every item on the page seen by this run (one UPDATE), creates documents for
changed file items with one outbox row each, and moves the checkpoint, counters, and
heartbeat forward, conditional on the run lease. Cancellation is checked with a fresh
query before each page and every ``CONNECTOR_SYNC_CANCEL_CHECK_ITEMS`` items.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger, log_connector_event
from app.core.metrics_workers import record_connector_sync_page, record_worker_tenant_mismatch
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorContentError,
)
from app.domains.connectors.services.sync import lease
from app.domains.connectors.services.sync.common import source_id_str
from app.domains.connectors.services.sync.context import LoopState, RunContext, finalize_checkpoint
from app.domains.connectors.services.sync.scope import SyncScope
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.connector_sync import ConnectorSyncRun
from app.models.enums import ConnectorSyncRunStatus

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine

_logger = get_logger("connectors.sync_engine")


@dataclass
class _Chunk:
    """Counters of one slice of a page."""

    upserted: int = 0
    deleted: int = 0


async def load_run(session: AsyncSession, ctx: RunContext) -> ConnectorSyncRun:
    """The run with its connection and provider, refreshed from the database."""
    result = await session.execute(
        select(ConnectorSyncRun)
        .options(
            selectinload(ConnectorSyncRun.connection).selectinload(ConnectorConnection.provider)
        )
        .where(
            ConnectorSyncRun.id == ctx.run_id,
            ConnectorSyncRun.organization_id == ctx.organization_id,
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def is_cancelled_now(scope: SyncScope, ctx: RunContext) -> bool:
    async with scope.transaction() as session:
        status = (
            await session.execute(
                select(ConnectorSyncRun.status).where(ConnectorSyncRun.id == ctx.run_id)
            )
        ).scalar_one_or_none()
    return status == ConnectorSyncRunStatus.cancelled.value


class SyncPager:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    async def run_pages(self, scope: SyncScope, ctx: RunContext) -> bool:
        """Page until the provider has no more pages; False when the run was cancelled."""
        while not ctx.state.paging_done:
            if await is_cancelled_now(scope, ctx):
                return False
            fetch_cursor = dict(ctx.state.cursor)
            page = await self._fetch(scope, ctx, fetch_cursor)
            async with scope.transaction() as session:
                new_state, cancelled = await self._write_page(session, ctx, page, fetch_cursor)
            ctx.state = new_state
            if cancelled:
                return False
            record_connector_sync_page(ctx.provider_key, ctx.mode)
        return True

    async def heartbeat(self, scope: SyncScope, ctx: RunContext) -> None:
        async with scope.transaction() as session:
            await lease.owned_update(
                session,
                run_id=ctx.run_id,
                owner=ctx.owner,
                values={"heartbeat_at": datetime.now(UTC)},
            )

    async def _fetch(self, scope: SyncScope, ctx: RunContext, cursor: dict) -> Any:
        fetcher = self.engine.fetcher

        async def beat() -> None:
            await self.heartbeat(scope, ctx)

        try:
            return await fetcher.fetch_with_backoff(ctx, cursor, beat)
        except ConnectorAuthError:
            # OAuth connections: refresh the token once and retry the same page.
            if not ctx.has_credential:
                raise
            refreshed = await self._refresh_credential(scope, ctx)
            if refreshed is None:
                raise
            ctx.decrypted = refreshed
            return await fetcher.fetch_with_backoff(ctx, cursor, beat)

    async def _refresh_credential(self, scope: SyncScope, ctx: RunContext) -> dict | None:
        engine = self.engine
        async with scope.transaction() as session:
            run = await load_run(session, ctx)
            credential = await engine.repository.get_current_credential(
                session, organization_id=ctx.organization_id, connection_id=ctx.connection_id
            )
            if credential is None:
                return None
            return await engine.fetcher.refreshed_credential(
                session,
                connection=run.connection,
                credential=credential,
                organization_id=ctx.organization_id,
            )

    async def _write_page(
        self, session: AsyncSession, ctx: RunContext, page: Any, fetch_cursor: dict
    ) -> tuple[LoopState, bool]:
        run = await load_run(session, ctx)
        connection = run.connection
        items = list(page.items)
        check_every = settings.connector_sync_cancel_check_items
        seen: list[str] = []
        known: dict[str, ExternalItem] = {}
        total = _Chunk()
        processed = 0
        cancelled = False
        for start in range(0, len(items), check_every):
            if start and await self.engine.writer.is_cancelled(session, run_id=run.id):
                cancelled = True
                break
            chunk = items[start : start + check_every]
            if ctx.incremental:
                part = await self._apply_delta_chunk(session, ctx, run, connection, chunk, seen)
            else:
                part = await self._apply_full_chunk(
                    session, ctx, run, connection, chunk, seen, known
                )
            total.upserted += part.upserted
            total.deleted += part.deleted
            processed += len(chunk)
        await self.engine.differ.mark_seen(session, run, seen)

        state = replace(
            ctx.state,
            items_seen=ctx.state.items_seen + processed,
            items_upserted=ctx.state.items_upserted + total.upserted,
            items_deleted=ctx.state.items_deleted + total.deleted,
        )
        now = datetime.now(UTC)
        values: dict[str, Any] = {**state.counters(), "heartbeat_at": now}
        if not cancelled:
            state.pages_committed += 1
            if page.has_more and page.next_cursor is not None:
                state.cursor = dict(page.next_cursor)
                checkpoint = state.cursor
            else:
                state.paging_done = True
                state.cursor_after = (
                    dict(page.next_cursor or fetch_cursor) if ctx.incremental else fetch_cursor
                )
                checkpoint = finalize_checkpoint(state.cursor_after)
            values.update(
                checkpoint_cursor=checkpoint,
                checkpoint_at=now,
                pages_committed=state.pages_committed,
            )
        await lease.owned_update(session, run_id=ctx.run_id, owner=ctx.owner, values=values)
        _logger.info(
            "connector.sync.page_committed",
            sync_run_id=str(ctx.run_id),
            organization_id=str(ctx.organization_id),
            provider_key=ctx.provider_key,
            mode=ctx.mode,
            page_items=processed,
            pages_committed=state.pages_committed,
            items_seen=state.items_seen,
            cancelled=cancelled,
        )
        return state, cancelled

    def _tenant_item(self, ctx: RunContext, item: Any) -> Any:
        """The item bound to the run's connection, or None when it names another tenant."""
        connection_id = getattr(item, "connection_id", None)
        if item.organization_id != ctx.organization_id or (
            connection_id is not None and connection_id != ctx.connection_id
        ):
            record_worker_tenant_mismatch("connectors.sync.run")
            _logger.warning(
                "connector.sync.item.tenant_mismatch",
                sync_run_id=str(ctx.run_id),
                organization_id=str(ctx.organization_id),
                provider_key=ctx.provider_key,
            )
            return None
        if connection_id is None:
            return item.model_copy(update={"connection_id": ctx.connection_id})
        return item

    async def _ingest(
        self,
        session: AsyncSession,
        ctx: RunContext,
        run: ConnectorSyncRun,
        connection: ConnectorConnection,
        item: Any,
    ) -> None:
        engine = self.engine
        pending = await engine._maybe_ingest_file_item(
            session,
            run=run,
            connection=connection,
            adapter=ctx.adapter,
            norm_item=item,
            decrypted_credential=ctx.decrypted,
        )
        if pending is not None:
            await engine.writer.enqueue_document(session, run, *pending)

    async def _apply_full_chunk(
        self,
        session: AsyncSession,
        ctx: RunContext,
        run: ConnectorSyncRun,
        connection: ConnectorConnection,
        chunk: list[Any],
        seen: list[str],
        known: dict[str, ExternalItem],
    ) -> _Chunk:
        part = _Chunk()
        items = [bound for item in chunk if (bound := self._tenant_item(ctx, item)) is not None]
        for item, changed in await self.engine.differ.apply_full_chunk(session, run, items, known):
            seen.append(item.provider_item_id)
            if changed:
                part.upserted += 1
                await self._ingest(session, ctx, run, connection, item)
        return part

    async def _apply_delta_chunk(
        self,
        session: AsyncSession,
        ctx: RunContext,
        run: ConnectorSyncRun,
        connection: ConnectorConnection,
        chunk: list[Any],
        seen: list[str],
    ) -> _Chunk:
        engine = self.engine
        part = _Chunk()
        for delta_item in chunk:
            if delta_item.is_deleted or delta_item.permission_revoked:
                if await engine._tombstone_item(session, run, delta_item):
                    part.deleted += 1
                continue
            if delta_item.item is None:
                continue
            item = self._tenant_item(ctx, delta_item.item)
            if item is None:
                continue
            seen.append(item.provider_item_id)
            try:
                if await engine._upsert_item_if_changed(session, run, item):
                    part.upserted += 1
                    await self._ingest(session, ctx, run, connection, item)
            except ConnectorContentError:
                await self._record_content_skip(session, run, item)
        return part

    async def _record_content_skip(
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
