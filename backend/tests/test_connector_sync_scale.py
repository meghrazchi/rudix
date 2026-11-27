"""R06-11: connector sync at tenant scale (per-page commits, cancellation, caps, tenancy).

Runs ``ConnectorSyncEngine.run_sync`` with a session factory, as the worker does, over a
SQLite file where every session has its own connection, so a page commit is visible to
other sessions exactly as it would be on PostgreSQL. The fake provider serves pages of
1,000 items (``ScaleAdapter``, built on the F241 ``FakeProviderAdapter``).
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.models.connector import ExternalItem
from app.models.connector_sync import ConnectorSyncRun
from app.models.document import Document
from tests.connector_sync_support import (
    PAGE,
    SqliteDb,
    cancel,
    count,
    item_counts,
    load_run_row,
    make_engine,
    outbox_rows,
    queue_run,
    scale_adapter,
    seed_tenant,
    sqlite_factory,
)

TOTAL = 20_000


@pytest_asyncio.fixture
async def db(sqlite_template_db: Path, tmp_path: Path) -> AsyncIterator[SqliteDb]:
    async for value in sqlite_factory(sqlite_template_db, tmp_path):
        yield value


@pytest.fixture
def published() -> Any:
    """Record outbox publications instead of reaching a broker."""
    calls: list[Any] = []
    with (
        patch("app.application.outbox._publish", side_effect=lambda d: calls.append(d)),
        patch(
            "app.domains.connectors.services.ingestion_bridge._upload_to_storage",
            new=AsyncMock(),
        ),
    ):
        yield calls


async def _tenant(db: SqliteDb) -> Any:
    async with db.factory() as session, session.begin():
        return await seed_tenant(session)


@pytest.mark.asyncio
async def test_full_sync_commits_each_page_and_dispatches_documents(
    db: SqliteDb, published: list[Any]
) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, TOTAL, file_every=100)
    observed: list[tuple[int, int, int, dict | None]] = []

    async def peek(offset: int) -> None:
        # Runs while no transaction of the sync is open: what has another session seen?
        run = await load_run_row(db.factory, run_id)
        live, _ = await item_counts(db.factory, tenant)
        observed.append((offset, live, run.pages_committed, run.checkpoint_cursor))

    adapter.on_fetch = peek
    run_id = await queue_run(db.factory, tenant)
    result = await make_engine(adapter, with_bridge=True).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id, lease_owner="task-1"
    )

    assert result.status == "completed"
    assert (result.items_seen, result.items_upserted, result.pages_committed) == (
        TOTAL,
        TOTAL,
        TOTAL // PAGE,
    )
    assert result.pending_document_ids == []
    # Before page 3 is fetched, pages 1 and 2 and their checkpoint are committed.
    assert observed[2] == (2 * PAGE, 2 * PAGE, 2, {"offset": 2 * PAGE})
    run = await load_run_row(db.factory, run_id)
    assert run.status == "completed" and run.lease_owner is None
    assert run.checkpoint_at is not None and run.pages_committed == TOTAL // PAGE
    assert await item_counts(db.factory, tenant) == (TOTAL, 0)
    docs = await count(db.factory, Document, Document.organization_id == tenant.org_id)
    assert docs == TOTAL // 100
    rows = await outbox_rows(db.factory, tenant)
    assert len(rows) == docs and len(published) == docs
    assert {r.task_name for r in rows} == {"documents.process"}
    assert all(r.dedupe_key == f"connector:{run_id}:{r.kwargs['document_id']}" for r in rows)
    assert {r.status for r in rows} == {"published"}
    async with db.factory() as session:
        seen = await session.execute(
            select(ExternalItem.last_seen_sync_run_id)
            .where(ExternalItem.connection_id == tenant.connection_id)
            .distinct()
        )
        assert list(seen.scalars()) == [run_id]


@pytest.mark.asyncio
async def test_unchanged_resync_upserts_nothing_and_marks_items_seen(
    db: SqliteDb, published: list[Any]
) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 3 * PAGE, file_every=100)
    engine = make_engine(adapter, with_bridge=True)
    first = await queue_run(db.factory, tenant)
    await engine.run_sync(db.factory, sync_run_id=first, organization_id=tenant.org_id)
    second = await queue_run(db.factory, tenant, full=True)

    result = await engine.run_sync(db.factory, sync_run_id=second, organization_id=tenant.org_id)

    files = 3 * PAGE // 100
    assert result.status == "completed"
    # Unchanged file items are skipped. Non-file items have no SourceDocument, so the 0.5
    # rule ("no SourceDocument yet" counts as changed) still counts them as upserted.
    assert (result.items_seen, result.items_upserted, result.items_deleted) == (
        3 * PAGE,
        3 * PAGE - files,
        0,
    )
    assert (
        await count(db.factory, ExternalItem, ExternalItem.last_seen_sync_run_id == second)
        == 3 * PAGE
    )
    assert len(await outbox_rows(db.factory, tenant)) == files


async def _cancel_after_pages(db: SqliteDb, total: int, pages: int) -> tuple[Any, Any, float]:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, total)
    cancelled_at: list[float] = []

    async def cancel_on_page(offset: int) -> None:
        if offset == pages * PAGE:
            await cancel(db.factory, tenant, run_id)
            cancelled_at.append(time.monotonic())

    adapter.on_fetch = cancel_on_page
    run_id = await queue_run(db.factory, tenant)
    result = await make_engine(adapter).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id
    )
    stopped = time.monotonic() - cancelled_at[0]
    run = await load_run_row(db.factory, run_id)
    assert len(adapter.list_calls) == pages + 1
    return result, run, stopped


@pytest.mark.asyncio
async def test_cancel_after_page_k_stops_within_one_check_interval(db: SqliteDb) -> None:
    k = 7
    result, run, _ = await _cancel_after_pages(db, TOTAL, k)

    check = settings.connector_sync_cancel_check_items
    assert result.status == "cancelled"
    assert run.status == "cancelled" and run.lease_owner is None
    assert run.pages_committed == k
    assert run.checkpoint_cursor == {"offset": k * PAGE}
    # The cancel landed while page k+1 was being fetched; the page stops at its first check.
    assert k * PAGE < run.items_seen <= k * PAGE + check
    assert result.items_seen == run.items_seen


@pytest.mark.skipif(
    os.environ.get("RUDIX_RUN_SLOW_TESTS") != "1", reason="set RUDIX_RUN_SLOW_TESTS=1"
)
@pytest.mark.slow
@pytest.mark.timeout(600)
@pytest.mark.asyncio
async def test_cancel_100k_item_sync_within_one_check_interval(db: SqliteDb) -> None:
    k = 60
    result, run, stopped = await _cancel_after_pages(db, 100_000, k)

    assert result.status == "cancelled" and run.pages_committed == k
    assert run.items_seen <= k * PAGE + settings.connector_sync_cancel_check_items
    print(f"cancel_to_stop_seconds={stopped:.3f} items_seen={run.items_seen}")
    assert stopped < 10.0


@pytest.mark.asyncio
async def test_cancel_before_tombstones_keeps_paging_checkpoint(db: SqliteDb) -> None:
    """A cancel during the last (short) page is seen before the tombstone phase starts."""
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, PAGE + 20)

    async def cancel_on_last(offset: int) -> None:
        if offset == PAGE:
            await cancel(db.factory, tenant, run_id)

    adapter.on_fetch = cancel_on_last
    run_id = await queue_run(db.factory, tenant)
    result = await make_engine(adapter).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id
    )

    assert result.status == "cancelled" and result.items_seen == PAGE + 20
    run = await load_run_row(db.factory, run_id)
    assert run.pages_committed == 2
    assert run.checkpoint_cursor == {"_rudix_phase": "finalize", "cursor_after": {"offset": PAGE}}


@pytest.mark.asyncio
async def test_lease_lost_mid_run_rolls_back_the_page(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 3 * PAGE)

    async def steal(offset: int) -> None:
        if offset == PAGE:
            async with db.factory() as session, session.begin():
                run = await session.get(ConnectorSyncRun, run_id)
                assert run is not None
                run.lease_owner = "another-worker"

    adapter.on_fetch = steal
    run_id = await queue_run(db.factory, tenant)
    result = await make_engine(adapter).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id, lease_owner="task-1"
    )

    assert result.status == "lease_lost"
    run = await load_run_row(db.factory, run_id)
    assert (run.status, run.lease_owner, run.pages_committed) == ("running", "another-worker", 1)
    assert await item_counts(db.factory, tenant) == (PAGE, 0)


@pytest.mark.isolation
@pytest.mark.asyncio
async def test_run_of_org_a_never_writes_org_b_rows(db: SqliteDb) -> None:
    tenant_a = await _tenant(db)
    tenant_b = await _tenant(db)
    # A misbehaving adapter stamps some items of org A's connection with org B.
    adapter = scale_adapter(
        tenant_a, 2 * PAGE, foreign_org={i: tenant_b.org_id for i in range(0, 2 * PAGE, 7)}
    )
    run_id = await queue_run(db.factory, tenant_a)

    result = await make_engine(adapter).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant_a.org_id
    )

    foreign = len(range(0, 2 * PAGE, 7))
    assert result.status == "completed"
    assert result.items_upserted == 2 * PAGE - foreign
    assert (
        await count(db.factory, ExternalItem, ExternalItem.organization_id == tenant_b.org_id) == 0
    )
    assert (
        await count(db.factory, ExternalItem, ExternalItem.organization_id == tenant_a.org_id)
        == 2 * PAGE - foreign
    )


@pytest.mark.isolation
@pytest.mark.asyncio
async def test_run_sync_refuses_a_run_of_another_organization(db: SqliteDb) -> None:
    from app.domains.connectors.services.sync_engine import SyncEngineError

    tenant_a = await _tenant(db)
    tenant_b = await _tenant(db)
    run_id = await queue_run(db.factory, tenant_a)

    with pytest.raises(SyncEngineError):
        await make_engine(scale_adapter(tenant_a, 10)).run_sync(
            db.factory, sync_run_id=run_id, organization_id=tenant_b.org_id
        )
    run = await load_run_row(db.factory, run_id)
    assert run.status == "queued" and run.lease_owner is None
