"""R06-11: due-job polling, the stale-run sweep, and the connectors.sync.run task."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.connectors.services.sync.schedule import MANUAL_ONLY_NEXT_RUN_AT
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.workers import connector_sync_tasks
from tests.connector_sync_support import (
    SqliteDb,
    load_job_row,
    load_run_row,
    make_engine,
    queue_run,
    scale_adapter,
    seed_tenant,
    sqlite_factory,
)


@pytest_asyncio.fixture
async def db(sqlite_template_db: Path, tmp_path: Path) -> AsyncIterator[SqliteDb]:
    async for value in sqlite_factory(sqlite_template_db, tmp_path):
        yield value


async def _tenant(db: SqliteDb, schedule: dict | None = None) -> Any:
    async with db.factory() as session, session.begin():
        return await seed_tenant(session, schedule=schedule)


async def _poll(db: SqliteDb) -> list[tuple[UUID, UUID]]:
    async with db.factory() as session, session.begin():
        return await make_engine(None).dispatch_due_syncs(session)


async def _set_job(db: SqliteDb, job_id: UUID, **values: Any) -> None:
    async with db.factory() as session, session.begin():
        job = await session.get(ConnectorSyncJob, job_id)
        assert job is not None
        for key, value in values.items():
            setattr(job, key, value)


def _utc(value: datetime | None) -> datetime:
    assert value is not None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# -- due-job polling -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_queues_a_due_job_and_moves_next_run_at(db: SqliteDb) -> None:
    tenant = await _tenant(db, {"type": "interval", "interval_minutes": 30})
    await _set_job(db, tenant.job_id, cursor_json={"delta": "abc"})
    before = datetime.now(UTC)

    dispatched = await _poll(db)

    assert [org for _, org in dispatched] == [tenant.org_id]
    run = await load_run_row(db.factory, dispatched[0][0])
    assert (run.status, run.trigger_type, run.cursor_before_json) == (
        "queued",
        "scheduled",
        {"delta": "abc"},
    )
    job = await load_job_row(db.factory, tenant.job_id)
    assert _utc(job.next_run_at) >= before + timedelta(minutes=30)
    assert await _poll(db) == []


@pytest.mark.asyncio
async def test_poll_stores_next_run_at_for_a_job_that_is_not_due(db: SqliteDb) -> None:
    tenant = await _tenant(db, {"type": "interval", "interval_minutes": 60})
    last = datetime.now(UTC) - timedelta(minutes=10)
    await _set_job(db, tenant.job_id, last_run_at=last)

    assert await _poll(db) == []
    job = await load_job_row(db.factory, tenant.job_id)
    assert abs(_utc(job.next_run_at) - (last + timedelta(minutes=60))) < timedelta(seconds=1)


@pytest.mark.asyncio
async def test_poll_parks_manual_only_jobs(db: SqliteDb) -> None:
    tenant = await _tenant(db, {"type": "manual_only"})
    assert await _poll(db) == []
    job = await load_job_row(db.factory, tenant.job_id)
    assert _utc(job.next_run_at) == MANUAL_ONLY_NEXT_RUN_AT


@pytest.mark.asyncio
async def test_poll_dispatches_once_next_run_at_has_passed(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    await _set_job(db, tenant.job_id, next_run_at=datetime.now(UTC) + timedelta(hours=1))
    assert await _poll(db) == []
    await _set_job(db, tenant.job_id, next_run_at=datetime.now(UTC) - timedelta(seconds=1))
    assert len(await _poll(db)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", ["org", "connection"])
async def test_poll_honours_concurrency_caps(
    db: SqliteDb, monkeypatch: pytest.MonkeyPatch, cap: str
) -> None:
    monkeypatch.setattr(settings, f"connector_sync_max_concurrent_per_{cap}", 1)
    tenant = await _tenant(db)
    async with db.factory() as session, session.begin():
        await make_engine(None).create_sync_job(
            session,
            organization_id=tenant.org_id,
            connection_id=tenant.connection_id,
            name="second",
        )

    assert len(await _poll(db)) == 1  # two due jobs, one slot
    assert await _poll(db) == []  # the queued run holds the slot


# -- stale-run sweep -------------------------------------------------------------------


@asynccontextmanager
async def _maintenance(db: SqliteDb) -> AsyncIterator[AsyncSession]:
    async with db.factory() as session:
        yield session


async def _set_run(db: SqliteDb, run_id: UUID, **values: Any) -> None:
    async with db.factory() as session, session.begin():
        run = await session.get(ConnectorSyncRun, run_id)
        assert run is not None
        for key, value in values.items():
            setattr(run, key, value)


@pytest.mark.asyncio
async def test_reaper_requeues_stale_runs_only(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    stale = await queue_run(db.factory, tenant)
    old = datetime.now(UTC) - timedelta(seconds=settings.connector_sync_stale_seconds + 60)
    await _set_run(db, stale, status="running", lease_owner="dead-worker", heartbeat_at=old)
    other = await _tenant(db)
    waiting = await queue_run(db.factory, other)
    future = datetime.now(UTC) + timedelta(hours=1)
    await _set_run(db, waiting, status="running", lease_owner=None, heartbeat_at=future)

    with (
        patch.object(connector_sync_tasks, "maintenance_session", lambda: _maintenance(db)),
        patch.object(connector_sync_tasks.celery_app, "send_task") as send_task,
    ):
        outcome = await connector_sync_tasks._reap_stale_async()

    assert outcome == {"requeued": 1}
    send_task.assert_called_once_with(
        "connectors.sync.run",
        kwargs={"sync_run_id": str(stale), "organization_id": str(tenant.org_id)},
    )
    run = await load_run_row(db.factory, stale)
    assert run.lease_owner is None and _utc(run.heartbeat_at) > old
    assert (await load_run_row(db.factory, waiting)).heartbeat_at is not None


# -- connectors.sync.run task ----------------------------------------------------------


@pytest.mark.asyncio
async def test_task_body_runs_with_one_session_per_page(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 2500)
    run_id = await queue_run(db.factory, tenant)
    engine = make_engine(adapter)

    with (
        patch.object(connector_sync_tasks, "SessionLocal", db.factory),
        patch.object(connector_sync_tasks, "ConnectorSyncEngine", return_value=engine),
    ):
        outcome = await connector_sync_tasks._run_sync_async(
            sync_run_id=str(run_id), organization_id=str(tenant.org_id), lease_owner="t-1"
        )

    assert outcome["status"] == "completed"
    assert (outcome["items_seen"], outcome["pages_committed"]) == (2500, 3)
    assert outcome["requeue_after_seconds"] is None


@pytest.mark.asyncio
async def test_task_body_maps_engine_errors_to_permanent_failures(db: SqliteDb) -> None:
    from app.workers.base_task import PermanentTaskError

    with patch.object(connector_sync_tasks, "SessionLocal", db.factory):
        with pytest.raises(PermanentTaskError):
            await connector_sync_tasks._run_sync_async(
                sync_run_id=str(uuid4()), organization_id=str(uuid4())
            )
        with pytest.raises(PermanentTaskError):
            await connector_sync_tasks._run_sync_async(
                sync_run_id="not-a-uuid", organization_id=str(uuid4())
            )


@pytest.mark.parametrize(("countdown", "requeued"), [(3600, True), (None, False)])
def test_task_requeues_the_run_with_the_returned_countdown(
    countdown: int | None, requeued: bool
) -> None:
    run_id, org_id = str(uuid4()), str(uuid4())
    body = AsyncMock(return_value={"status": "running", "requeue_after_seconds": countdown})
    with (
        patch.object(connector_sync_tasks, "_run_sync_async", body),
        patch.object(connector_sync_tasks.run_connector_sync, "apply_async") as apply_async,
    ):
        connector_sync_tasks.run_connector_sync.apply(
            kwargs={"sync_run_id": run_id, "organization_id": org_id}
        ).get()

    assert body.await_args is not None
    assert body.await_args.kwargs["lease_owner"]  # the Celery request id
    if requeued:
        apply_async.assert_called_once_with(
            kwargs={"sync_run_id": run_id, "organization_id": org_id}, countdown=countdown
        )
    else:
        apply_async.assert_not_called()


def test_reap_task_and_beat_entry_are_registered() -> None:
    from app.workers.celery_app import BEAT_SCHEDULE, TASK_ROUTES

    assert BEAT_SCHEDULE["connector-sync-reap"]["task"] == "connectors.sync.reap"
    assert (
        BEAT_SCHEDULE["connector-sync-reap"]["schedule"]
        == settings.connector_sync_reap_interval_seconds
    )
    assert TASK_ROUTES["connectors.sync.reap"]["queue"] == settings.celery_queue_connector_sync
    reap = MagicMock(return_value={"requeued": 0})
    with patch.object(connector_sync_tasks, "_reap_stale_async", AsyncMock(side_effect=reap)):
        assert connector_sync_tasks.reap_stale_connector_syncs.apply().get() == {"requeued": 0}


# -- API contract ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_run_response_reports_checkpoint_fields(db: SqliteDb) -> None:
    from app.interfaces.http.connector_sync import _run_response

    tenant = await _tenant(db)
    run_id = await queue_run(db.factory, tenant)
    fresh = _run_response(await load_run_row(db.factory, run_id))
    assert (fresh.checkpoint_at, fresh.pages_committed) == (None, 0)

    await make_engine(scale_adapter(tenant, 1500)).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id
    )
    done = _run_response(await load_run_row(db.factory, run_id))
    assert done.pages_committed == 2
    assert done.checkpoint_at is not None and datetime.fromisoformat(done.checkpoint_at)
