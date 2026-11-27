"""R06-11: resume from checkpoints, Retry-After handling, caps, leases, and the reaper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
import pytest_asyncio

from app.core.config import settings
from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorPermissionError,
    ConnectorRateLimitError,
)
from app.models.connector import ConnectorConnection
from app.models.connector_source import ExternalItemTombstone
from app.models.connector_sync import ConnectorSyncRun
from app.models.document import Document
from tests.connector_sync_support import (
    PAGE,
    SqliteDb,
    WorkerKilled,
    cancel,
    count,
    item_counts,
    item_id,
    load_run_row,
    make_engine,
    outbox_rows,
    queue_run,
    scale_adapter,
    seed_tenant,
    sqlite_factory,
)

TOTAL = 5 * PAGE


@pytest_asyncio.fixture
async def db(sqlite_template_db: Path, tmp_path: Path) -> AsyncIterator[SqliteDb]:
    async for value in sqlite_factory(sqlite_template_db, tmp_path):
        yield value


@pytest.fixture(autouse=True)
def _no_broker() -> Any:
    with (
        patch("app.application.outbox._publish", return_value=None),
        patch(
            "app.domains.connectors.services.ingestion_bridge._upload_to_storage",
            new=AsyncMock(),
        ),
    ):
        yield


async def _tenant(db: SqliteDb) -> Any:
    async with db.factory() as session, session.begin():
        return await seed_tenant(session)


async def _set_run(db: SqliteDb, run_id: UUID, **values: Any) -> None:
    async with db.factory() as session, session.begin():
        run = await session.get(ConnectorSyncRun, run_id)
        assert run is not None
        for key, value in values.items():
            setattr(run, key, value)


async def _run(db: SqliteDb, engine: Any, tenant: Any, run_id: UUID, owner: str) -> Any:
    return await engine.run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id, lease_owner=owner
    )


def _kill_at(offset: int) -> Any:
    fired: list[int] = []

    async def hook(at: int) -> None:
        if at == offset and not fired:
            fired.append(at)
            raise WorkerKilled()

    return hook


@pytest.mark.asyncio
async def test_worker_killed_after_page_k_resumes_at_page_k_plus_one(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    k = 3
    adapter = scale_adapter(tenant, TOTAL, file_every=50, on_fetch=_kill_at(k * PAGE))
    engine = make_engine(adapter, with_bridge=True)
    run_id = await queue_run(db.factory, tenant)

    with pytest.raises(WorkerKilled):
        await _run(db, engine, tenant, run_id, "task-1")
    run = await load_run_row(db.factory, run_id)
    assert (run.status, run.pages_committed, run.lease_owner) == ("running", k, "task-1")
    assert run.checkpoint_cursor == {"offset": k * PAGE} and run.items_seen == k * PAGE

    adapter.list_calls.clear()
    result = await _run(db, engine, tenant, run_id, "task-1")  # broker redelivery

    assert result.status == "completed"
    assert adapter.list_calls[0]["cursor"] == {"offset": k * PAGE}
    assert len(adapter.list_calls) == TOTAL // PAGE - k
    assert (result.items_seen, result.pages_committed, result.items_deleted) == (
        TOTAL,
        TOTAL // PAGE,
        0,
    )
    assert await item_counts(db.factory, tenant) == (TOTAL, 0)
    docs = await count(db.factory, Document, Document.organization_id == tenant.org_id)
    assert docs == TOTAL // 50
    rows = await outbox_rows(db.factory, tenant)
    assert len(rows) == docs and len({r.dedupe_key for r in rows}) == docs
    assert (
        await count(db.factory, ExternalItemTombstone, ExternalItemTombstone.sync_run_id == run_id)
        == 0
    )


@pytest.mark.asyncio
async def test_worker_killed_mid_page_rolls_the_page_back_without_duplicates(
    db: SqliteDb,
) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, TOTAL, file_every=50)
    fired: list[str] = []

    async def die_on_download(provider_item_id: str) -> None:
        if provider_item_id == item_id(2 * PAGE + 500) and not fired:
            fired.append(provider_item_id)
            raise WorkerKilled()

    adapter.on_download = die_on_download
    engine = make_engine(adapter, with_bridge=True)
    run_id = await queue_run(db.factory, tenant)
    with pytest.raises(WorkerKilled):
        await _run(db, engine, tenant, run_id, "task-1")
    # Page 3 was rolled back: two pages of items, documents, and outbox rows remain.
    assert await item_counts(db.factory, tenant) == (2 * PAGE, 0)
    assert len(await outbox_rows(db.factory, tenant)) == 2 * PAGE // 50

    # A different worker takes over once the heartbeat is stale.
    held = await _run(db, engine, tenant, run_id, "task-2")
    assert held.status == "running" and "leased" in (held.error_message or "")
    stale = datetime.now(UTC) - timedelta(seconds=settings.connector_sync_stale_seconds + 5)
    await _set_run(db, run_id, heartbeat_at=stale)
    result = await _run(db, engine, tenant, run_id, "task-2")

    assert result.status == "completed" and result.items_seen == TOTAL
    docs = await count(db.factory, Document, Document.organization_id == tenant.org_id)
    assert docs == TOTAL // 50
    assert len(await outbox_rows(db.factory, tenant)) == docs


@pytest.mark.asyncio
async def test_full_sync_after_resume_tombstones_exactly_the_unseen_items(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    first = scale_adapter(tenant, TOTAL)
    engine = make_engine(first)
    await _run(db, engine, tenant, await queue_run(db.factory, tenant), "seed")

    gone = {5, 777, 1999, 2000, 3001, 4999}
    second = scale_adapter(tenant, TOTAL, skip=gone, on_fetch=_kill_at(2 * PAGE))
    engine = make_engine(second)
    run_id = await queue_run(db.factory, tenant, full=True)
    with pytest.raises(WorkerKilled):
        await _run(db, engine, tenant, run_id, "task-1")
    result = await _run(db, engine, tenant, run_id, "task-1")

    assert result.status == "completed"
    assert result.items_deleted == len(gone)
    assert result.items_seen == TOTAL - len(gone)
    assert await item_counts(db.factory, tenant) == (TOTAL - len(gone), len(gone))
    tombstoned = await count(
        db.factory, ExternalItemTombstone, ExternalItemTombstone.sync_run_id == run_id
    )
    assert tombstoned == len(gone)


@pytest.mark.asyncio
async def test_worker_killed_during_tombstones_resumes_without_refetching(
    db: SqliteDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await _tenant(db)
    engine = make_engine(scale_adapter(tenant, 2 * PAGE))
    await _run(db, engine, tenant, await queue_run(db.factory, tenant), "seed")
    monkeypatch.setattr(settings, "connector_sync_tombstone_batch_size", 3)
    adapter = scale_adapter(tenant, 2 * PAGE, skip=set(range(0, 20)))
    engine = make_engine(adapter)
    original = engine.differ.tombstone_unseen_batch
    calls: list[int] = []

    async def die_on_second_batch(*args: Any, **kwargs: Any) -> int:
        calls.append(1)
        if len(calls) == 2:
            raise WorkerKilled()
        return await original(*args, **kwargs)

    engine.differ.tombstone_unseen_batch = die_on_second_batch  # type: ignore[method-assign]
    run_id = await queue_run(db.factory, tenant, full=True)
    with pytest.raises(WorkerKilled):
        await _run(db, engine, tenant, run_id, "task-1")
    run = await load_run_row(db.factory, run_id)
    assert run.checkpoint_cursor is not None and run.checkpoint_cursor["_rudix_phase"] == "finalize"
    assert run.items_deleted == 3

    adapter.list_calls.clear()
    result = await _run(db, engine, tenant, run_id, "task-1")
    assert adapter.list_calls == []
    assert result.status == "completed" and result.items_deleted == 20


@pytest.mark.asyncio
async def test_short_retry_after_backs_off_inside_the_run(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 3 * PAGE)
    hits: list[int] = []

    async def limit_page_two(offset: int) -> None:
        if offset == PAGE and len(hits) < 2:
            hits.append(offset)
            raise ConnectorRateLimitError("429", retry_after_seconds=20)

    adapter.on_fetch = limit_page_two
    engine = make_engine(adapter)
    run_id = await queue_run(db.factory, tenant)
    result = await _run(db, engine, tenant, run_id, "task-1")

    assert result.status == "completed" and result.items_seen == 3 * PAGE
    assert result.requeue_after_seconds is None
    # 20 s in steps of at most 15 s, a heartbeat after each step, twice.
    assert [c.args[0] for c in engine.sleep.await_args_list] == [15.0, 5.0, 15.0, 5.0]


@pytest.mark.asyncio
async def test_long_retry_after_checkpoints_and_requeues_instead_of_failing(
    db: SqliteDb,
) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 3 * PAGE)
    hits: list[int] = []

    async def limit_once(offset: int) -> None:
        if offset == 2 * PAGE and not hits:
            hits.append(offset)
            raise ConnectorRateLimitError("429", retry_after_seconds=3600)

    adapter.on_fetch = limit_once
    engine = make_engine(adapter)
    run_id = await queue_run(db.factory, tenant)
    deferred = await _run(db, engine, tenant, run_id, "task-1")

    assert deferred.status == "running" and deferred.requeue_after_seconds == 3600
    run = await load_run_row(db.factory, run_id)
    assert (run.status, run.lease_owner, run.pages_committed) == ("running", None, 2)
    assert run.checkpoint_cursor == {"offset": 2 * PAGE}
    assert run.heartbeat_at is not None
    assert run.heartbeat_at.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(minutes=50)
    engine.sleep.assert_not_awaited()

    result = await _run(db, engine, tenant, run_id, "task-2")  # the re-enqueued message
    assert result.status == "completed" and result.items_seen == 3 * PAGE


@pytest.mark.asyncio
async def test_inline_retries_exhausted_requeue_with_the_provider_countdown(
    db: SqliteDb,
) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, PAGE)

    async def always_limited(offset: int) -> None:
        raise ConnectorRateLimitError("429", retry_after_seconds=2)

    adapter.on_fetch = always_limited
    engine = make_engine(adapter)
    run_id = await queue_run(db.factory, tenant)
    result = await _run(db, engine, tenant, run_id, "task-1")

    assert result.requeue_after_seconds == 2
    assert engine.sleep.await_count == settings.connector_sync_max_inline_retries


@pytest.mark.asyncio
async def test_rate_limit_after_cancel_reports_cancelled(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, PAGE)

    async def cancel_then_limit(offset: int) -> None:
        await cancel(db.factory, tenant, run_id)
        raise ConnectorRateLimitError("429", retry_after_seconds=999)

    adapter.on_fetch = cancel_then_limit
    run_id = await queue_run(db.factory, tenant)
    result = await _run(db, make_engine(adapter), tenant, run_id, "task-1")
    assert result.status == "cancelled"
    assert (await load_run_row(db.factory, run_id)).lease_owner is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ConnectorPermissionError("forbidden"), "permission_denied"),
        (RuntimeError("provider exploded"), "sync_error"),
        (ConnectorAuthError("token expired"), "auth_error"),
    ],
)
async def test_provider_errors_fail_the_run(db: SqliteDb, error: Exception, code: str) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 2 * PAGE)

    async def fail_page_two(offset: int) -> None:
        if offset == PAGE:
            raise error

    adapter.on_fetch = fail_page_two
    run_id = await queue_run(db.factory, tenant)
    result = await _run(db, make_engine(adapter), tenant, run_id, "task-1")

    assert result.status == "failed"
    run = await load_run_row(db.factory, run_id)
    assert run.error_details_json["code"] == code
    assert (run.pages_committed, run.lease_owner) == (1, None)
    async with db.factory() as session:
        connection = await session.get(ConnectorConnection, tenant.connection_id)
        assert connection is not None
        assert (connection.status == "error") is (code == "auth_error")


@pytest.mark.asyncio
async def test_failure_after_cancel_reports_cancelled(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, PAGE)

    async def cancel_then_fail(offset: int) -> None:
        await cancel(db.factory, tenant, run_id)
        raise RuntimeError("boom")

    adapter.on_fetch = cancel_then_fail
    run_id = await queue_run(db.factory, tenant)
    result = await _run(db, make_engine(adapter), tenant, run_id, "task-1")
    assert result.status == "cancelled"
    assert (await load_run_row(db.factory, run_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_oauth_auth_error_refreshes_and_retries_the_same_page(db: SqliteDb) -> None:
    from app.models.connector import ConnectorProvider
    from app.models.connector_credential import ConnectorCredential

    tenant = await _tenant(db)
    async with db.factory() as session, session.begin():
        connection = await session.get(ConnectorConnection, tenant.connection_id)
        assert connection is not None
        provider = await session.get(ConnectorProvider, connection.provider_id)
        assert provider is not None
        provider.auth_type = "oauth2"
        session.add(
            ConnectorCredential(
                organization_id=tenant.org_id,
                connection_id=tenant.connection_id,
                auth_type="oauth2",
                encrypted_payload="dummy",
                encryption_key_id="k1",
                encryption_algorithm="AES-GCM",
                secret_fingerprint="f" * 64,
                scopes_json=[],
                metadata_json={},
                version=1,
                is_current=True,
                status="active",
            )
        )
    adapter = scale_adapter(tenant, 2 * PAGE)
    hits: list[int] = []

    async def expire_once(offset: int) -> None:
        if offset == PAGE and not hits:
            hits.append(offset)
            raise ConnectorAuthError("401")

    adapter.on_fetch = expire_once
    engine = make_engine(adapter)
    engine.credential_vault.decrypt = MagicMock(return_value={"token": "t"})  # type: ignore[method-assign]
    lifecycle = MagicMock()
    lifecycle.refresh_oauth_credential = AsyncMock()
    engine._oauth_lifecycle = lifecycle
    run_id = await queue_run(db.factory, tenant)

    result = await _run(db, engine, tenant, run_id, "task-1")

    assert result.status == "completed" and result.items_seen == 2 * PAGE
    lifecycle.refresh_oauth_credential.assert_awaited_once()
    assert [c["cursor"] for c in adapter.list_calls] == [{}, {"offset": PAGE}, {"offset": PAGE}]


@pytest.mark.asyncio
async def test_finished_run_is_not_run_again(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 10)
    engine = make_engine(adapter)
    run_id = await queue_run(db.factory, tenant)
    await _run(db, engine, tenant, run_id, "task-1")
    adapter.list_calls.clear()

    again = await _run(db, engine, tenant, run_id, "task-1")
    assert again.status == "completed" and adapter.list_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", ["org", "connection"])
async def test_concurrency_cap_leaves_the_run_queued(
    db: SqliteDb, monkeypatch: pytest.MonkeyPatch, cap: str
) -> None:
    monkeypatch.setattr(settings, f"connector_sync_max_concurrent_per_{cap}", 1)
    tenant = await _tenant(db)
    engine = make_engine(scale_adapter(tenant, 10))
    busy = await queue_run(db.factory, tenant)
    await _set_run(db, busy, status="running", lease_owner="other", heartbeat_at=datetime.now(UTC))
    async with db.factory() as session, session.begin():
        other_job = await engine.create_sync_job(
            session,
            organization_id=tenant.org_id,
            connection_id=tenant.connection_id,
            name="second job",
        )
        waiting = (
            await engine.trigger_manual_sync(
                session,
                organization_id=tenant.org_id,
                connection_id=tenant.connection_id,
                job_id=other_job.id,
            )
        ).id

    result = await _run(db, engine, tenant, waiting, "task-1")

    assert result.status == "queued"
    assert result.requeue_after_seconds == settings.connector_sync_cap_retry_seconds
    assert (await load_run_row(db.factory, waiting)).status == "queued"
    await _set_run(db, busy, status="completed", lease_owner=None)
    assert (await _run(db, engine, tenant, waiting, "task-1")).status == "completed"
