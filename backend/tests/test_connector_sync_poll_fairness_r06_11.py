"""R06-11 review: capped organizations must not starve other organizations' due jobs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio

from app.core.config import settings
from app.models.connector_sync import ConnectorSyncJob
from tests.connector_sync_support import (
    SqliteDb,
    make_engine,
    queue_run,
    seed_tenant,
    sqlite_factory,
)


@pytest_asyncio.fixture
async def db(sqlite_template_db: Path, tmp_path: Path) -> AsyncIterator[SqliteDb]:
    async for value in sqlite_factory(sqlite_template_db, tmp_path):
        yield value


async def _poll(db: SqliteDb) -> list[tuple[UUID, UUID]]:
    async with db.factory() as session, session.begin():
        return await make_engine(None).dispatch_due_syncs(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", ["org", "connection"])
async def test_jobs_over_a_cap_do_not_fill_the_poll_batch(
    db: SqliteDb, monkeypatch: pytest.MonkeyPatch, cap: str
) -> None:
    monkeypatch.setattr(settings, f"connector_sync_max_concurrent_per_{cap}", 1)
    monkeypatch.setattr(settings, "connector_sync_poll_batch_size", 3)
    early = datetime.now(UTC) - timedelta(hours=2)
    async with db.factory() as session, session.begin():
        busy = await seed_tenant(session)
        engine = make_engine(None)
        busy_jobs = [busy.job_id]
        for index in range(3):
            job = await engine.create_sync_job(
                session,
                organization_id=busy.org_id,
                connection_id=busy.connection_id,
                name=f"busy {index}",
            )
            busy_jobs.append(job.id)
        other = await seed_tenant(session)
    # The busy tenant already uses its one slot; its other jobs are due first.
    await queue_run(db.factory, busy)
    async with db.factory() as session, session.begin():
        for job_id in busy_jobs:
            job = await session.get(ConnectorSyncJob, job_id)
            assert job is not None
            job.next_run_at = early
        other_job = await session.get(ConnectorSyncJob, other.job_id)
        assert other_job is not None
        other_job.next_run_at = early + timedelta(hours=1)

    dispatched = await _poll(db)

    assert [org for _, org in dispatched] == [other.org_id]
