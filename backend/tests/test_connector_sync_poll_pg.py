"""R06-11 on PostgreSQL: one SKIP LOCKED due-job query, page commits, leases, caps."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.domains.connectors.services.sync import lease
from app.models.connector import ExternalItem
from app.models.connector_sync import ConnectorSyncRun
from app.models.organization import Organization
from tests.connector_sync_support import (
    PAGE,
    Tenant,
    cancel,
    item_counts,
    item_id,
    load_run_row,
    make_engine,
    queue_run,
    scale_adapter,
    seed_tenant,
)
from tests.query_count import count_queries

pytestmark = pytest.mark.requires_postgres

Factory = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def tenants(pg_session_factory: Factory) -> AsyncIterator[list[Tenant]]:
    created: list[Tenant] = []
    yield created
    async with pg_session_factory() as session, session.begin():
        await session.execute(
            delete(Organization).where(Organization.id.in_([t.org_id for t in created]))
        )


async def _committed_tenant(factory: Factory, tenants: list[Tenant]) -> Tenant:
    async with factory() as session, session.begin():
        tenant = await seed_tenant(session)
    tenants.append(tenant)
    return tenant


@pytest.fixture(autouse=True)
def _no_broker() -> Any:
    with patch("app.application.outbox._publish", return_value=None):
        yield


@pytest.mark.asyncio
async def test_due_poll_is_one_select_for_n_jobs(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "connector_sync_poll_batch_size", 1000)
    mine = [await seed_tenant(pg_session) for _ in range(6)]
    await pg_session.flush()

    with count_queries(pg_session) as counter:
        dispatched = await make_engine(None).dispatch_due_syncs(pg_session)

    selects = [s for s in counter.statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    assert "FOR UPDATE OF connector_sync_jobs SKIP LOCKED" in selects[0]
    assert "NOT (EXISTS" in selects[0] and "NULLS FIRST" in selects[0]
    assert {t.org_id for t in mine} <= {org for _, org in dispatched}


@pytest.mark.asyncio
async def test_concurrent_pollers_never_claim_the_same_job(
    pg_session_factory: Factory, tenants: list[Tenant]
) -> None:
    mine = {(await _committed_tenant(pg_session_factory, tenants)).org_id for _ in range(3)}
    engine = make_engine(None)
    async with pg_session_factory() as first, first.begin():
        claimed = await engine.dispatch_due_syncs(first)
        assert mine <= {org for _, org in claimed}
        async with pg_session_factory() as second, second.begin():
            # The first poller still holds its row locks: SKIP LOCKED, so no wait.
            other = await asyncio.wait_for(engine.dispatch_due_syncs(second), timeout=5)
            await second.rollback()
    assert not mine & {org for _, org in other}


@pytest.mark.asyncio
async def test_pages_commit_and_cancel_lands_inside_a_page(
    pg_session_factory: Factory, tenants: list[Tenant]
) -> None:
    tenant = await _committed_tenant(pg_session_factory, tenants)
    adapter = scale_adapter(tenant, 3 * PAGE)
    visible: list[tuple[int, int]] = []

    async def peek(offset: int) -> None:
        visible.append((offset, (await item_counts(pg_session_factory, tenant))[0]))

    adapter.on_fetch = peek
    engine = make_engine(adapter)
    original = engine._maybe_ingest_file_item

    async def cancel_mid_page(session: AsyncSession, **kwargs: Any) -> Any:
        if kwargs["norm_item"].provider_item_id == item_id(PAGE + 10):
            await cancel(pg_session_factory, tenant, run_id)  # another session, committed
        return await original(session, **kwargs)

    engine._maybe_ingest_file_item = cancel_mid_page  # type: ignore[method-assign]
    run_id = await queue_run(pg_session_factory, tenant)
    result = await engine.run_sync(
        pg_session_factory, sync_run_id=run_id, organization_id=tenant.org_id
    )

    assert visible == [(0, 0), (PAGE, PAGE)]
    assert result.status == "cancelled"
    run = await load_run_row(pg_session_factory, run_id)
    assert (run.status, run.pages_committed, run.checkpoint_cursor) == (
        "cancelled",
        1,
        {"offset": PAGE},
    )
    assert run.items_seen == PAGE + settings.connector_sync_cancel_check_items
    assert await item_counts(pg_session_factory, tenant) == (run.items_seen, 0)


@pytest.mark.asyncio
async def test_only_one_worker_takes_the_lease(
    pg_session_factory: Factory, tenants: list[Tenant]
) -> None:
    tenant = await _committed_tenant(pg_session_factory, tenants)
    run_id = await queue_run(pg_session_factory, tenant)
    now = datetime.now(UTC)
    async with pg_session_factory() as first:
        await first.begin()
        assert await lease.try_lease(first, run_id=run_id, owner="a", now=now)

        async def second_worker() -> bool:
            async with pg_session_factory() as second, second.begin():
                return await lease.try_lease(second, run_id=run_id, owner="b", now=now)

        contender = asyncio.create_task(second_worker())
        await asyncio.sleep(0.3)
        assert not contender.done()  # blocked on the row lock
        await first.commit()
    assert await contender is False
    assert (await load_run_row(pg_session_factory, run_id)).lease_owner == "a"


@pytest.mark.asyncio
async def test_org_cap_serializes_leases_with_an_advisory_lock(
    pg_session_factory: Factory, tenants: list[Tenant], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "connector_sync_max_concurrent_per_org", 1)
    tenant = await _committed_tenant(pg_session_factory, tenants)
    engine = make_engine(None)
    first_run = await queue_run(pg_session_factory, tenant)
    async with pg_session_factory() as session, session.begin():
        job = await engine.create_sync_job(
            session, organization_id=tenant.org_id, connection_id=tenant.connection_id, name="j2"
        )
        second_run = (
            await engine.trigger_manual_sync(
                session,
                organization_id=tenant.org_id,
                connection_id=tenant.connection_id,
                job_id=job.id,
            )
        ).id
    now = datetime.now(UTC)

    async def lease_if_free(run_id: UUID, owner: str, hold: float) -> str | None:
        async with pg_session_factory() as session, session.begin():
            run = await session.get(ConnectorSyncRun, run_id)
            assert run is not None
            reason = await lease.over_cap(session, run, now)
            if reason is None:
                await lease.try_lease(session, run_id=run_id, owner=owner, now=now)
                await asyncio.sleep(hold)
            return reason

    outcomes = await asyncio.gather(
        lease_if_free(first_run, "a", 0.3), lease_if_free(second_run, "b", 0.0)
    )
    assert sorted(outcomes, key=str) == [None, "org_cap"]


@pytest.mark.asyncio
async def test_reaper_releases_stale_runs_with_skip_locked(
    pg_session: AsyncSession,
) -> None:
    tenant = await seed_tenant(pg_session)
    run = ConnectorSyncRun(
        organization_id=tenant.org_id,
        sync_job_id=tenant.job_id,
        connection_id=tenant.connection_id,
        status="running",
        sync_version=1,
        lease_owner="dead",
        heartbeat_at=datetime.now(UTC) - timedelta(hours=2),
    )
    pg_session.add(run)
    await pg_session.flush()

    with count_queries(pg_session) as counter:
        rows = await lease.reap_stale_runs(pg_session, now=datetime.now(UTC), limit=10_000)

    assert (run.id, tenant.org_id) in [tuple(r) for r in rows]
    assert "SKIP LOCKED" in counter.matching("SELECT")[0]
    owner = await pg_session.scalar(
        select(ConnectorSyncRun.lease_owner).where(ConnectorSyncRun.id == run.id)
    )
    assert owner is None


@pytest.mark.isolation
@pytest.mark.asyncio
async def test_org_a_run_writes_no_org_b_rows_on_postgres(
    pg_session_factory: Factory, tenants: list[Tenant]
) -> None:
    tenant_a = await _committed_tenant(pg_session_factory, tenants)
    tenant_b = await _committed_tenant(pg_session_factory, tenants)
    adapter = scale_adapter(
        tenant_a, 300, foreign_org={i: tenant_b.org_id for i in range(0, 300, 3)}
    )
    run_id = await queue_run(pg_session_factory, tenant_a)
    with patch(
        "app.domains.connectors.services.ingestion_bridge._upload_to_storage", new=AsyncMock()
    ):
        result = await make_engine(adapter).run_sync(
            pg_session_factory, sync_run_id=run_id, organization_id=tenant_a.org_id
        )

    assert result.status == "completed" and result.items_upserted == 200
    async with pg_session_factory() as session:
        foreign = await session.scalar(
            select(ExternalItem.id).where(ExternalItem.organization_id == tenant_b.org_id)
        )
    assert foreign is None
