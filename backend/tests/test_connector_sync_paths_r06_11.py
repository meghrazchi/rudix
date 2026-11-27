"""R06-11: incremental pages and resume, changed items, ingestion skips, refresh failures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorContentError,
    DeltaItem,
    DeltaPage,
)
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_credential import ConnectorCredential
from app.models.connector_sync import ConnectorSyncJob
from app.models.usage import AuditLog
from tests.connector_sync_support import (
    PAGE,
    ScaleAdapter,
    SqliteDb,
    WorkerKilled,
    cancel,
    item_counts,
    item_id,
    load_job_row,
    load_run_row,
    make_engine,
    outbox_rows,
    queue_run,
    scale_adapter,
    seed_tenant,
    sqlite_factory,
)


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


@dataclass
class DeltaAdapter(ScaleAdapter):
    """Delta pages over a fixed list of ``DeltaItem`` objects, ``delta_page`` per page."""

    deltas: list[DeltaItem] = field(default_factory=list)
    delta_page: int = 10
    final_cursor: dict = field(default_factory=lambda: {"token": "next"})

    async def delta_sync(self, **kwargs: Any) -> DeltaPage:
        cursor = dict(kwargs["cursor"])
        self.delta_calls.append({"cursor": cursor})
        offset = int(cursor.get("delta_offset", 0))
        if self.on_fetch is not None:
            await self.on_fetch(offset)
        end = min(offset + self.delta_page, len(self.deltas))
        more = end < len(self.deltas)
        return DeltaPage(
            items=self.deltas[offset:end],
            next_cursor={"delta_offset": end} if more else self.final_cursor,
            has_more=more,
        )


async def _incremental_setup(db: SqliteDb, tenant: Any, total: int) -> Any:
    """A completed full sync of ``total`` items, leaving the job with a cursor."""
    engine = make_engine(scale_adapter(tenant, total))
    await engine.run_sync(
        db.factory, sync_run_id=await queue_run(db.factory, tenant), organization_id=tenant.org_id
    )
    async with db.factory() as session, session.begin():
        job = await session.get(ConnectorSyncJob, tenant.job_id)
        assert job is not None
        job.cursor_json = {"delta_offset": 0}


@pytest.mark.asyncio
async def test_incremental_sync_pages_resume_and_keep_delta_semantics(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    await _incremental_setup(db, tenant, 40)
    maker = scale_adapter(tenant, 40, version="v2")
    deltas = [DeltaItem(provider_item_id=item_id(i), is_deleted=True) for i in range(0, 5)]
    deltas += [DeltaItem(provider_item_id=item_id(i), permission_revoked=True) for i in (5, 6)]
    deltas += [
        DeltaItem(provider_item_id=item_id(i), item=maker.make_item(i)) for i in range(7, 30)
    ]
    deltas.append(DeltaItem(provider_item_id="missing", is_deleted=True))
    deltas.append(DeltaItem(provider_item_id="empty"))
    fired: list[int] = []

    async def kill_once(offset: int) -> None:
        if offset == 20 and not fired:
            fired.append(offset)
            raise WorkerKilled()

    adapter = DeltaAdapter(
        organization_id=tenant.org_id,
        connection_id=tenant.connection_id,
        deltas=deltas,
        on_fetch=kill_once,
    )
    engine = make_engine(adapter)
    run_id = await queue_run(db.factory, tenant)
    with pytest.raises(WorkerKilled):
        await engine.run_sync(
            db.factory, sync_run_id=run_id, organization_id=tenant.org_id, lease_owner="t"
        )
    assert (await load_run_row(db.factory, run_id)).checkpoint_cursor == {"delta_offset": 20}

    result = await engine.run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id, lease_owner="t"
    )

    assert result.status == "completed"
    assert (result.items_seen, result.items_upserted, result.items_deleted) == (32, 23, 7)
    assert result.cursor_after == {"token": "next"}
    assert [c["cursor"] for c in adapter.delta_calls] == [
        {"delta_offset": 0},
        {"delta_offset": 10},
        {"delta_offset": 20},
        {"delta_offset": 20},
        {"delta_offset": 30},
    ]
    assert await item_counts(db.factory, tenant) == (33, 7)
    assert (await load_job_row(db.factory, tenant.job_id)).cursor_json == {"token": "next"}


@pytest.mark.asyncio
async def test_incremental_content_errors_are_skipped(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    await _incremental_setup(db, tenant, 3)
    maker = scale_adapter(tenant, 3, version="v2")
    adapter = DeltaAdapter(
        organization_id=tenant.org_id,
        connection_id=tenant.connection_id,
        deltas=[DeltaItem(provider_item_id=item_id(i), item=maker.make_item(i)) for i in range(3)],
    )
    engine = make_engine(adapter)
    original = engine.differ.upsert_item_if_changed

    async def unreadable_first(session: Any, run: Any, item: Any) -> bool:
        if item.provider_item_id == item_id(0):
            raise ConnectorContentError("unreadable")
        return await original(session, run, item)

    engine.differ.upsert_item_if_changed = unreadable_first  # type: ignore[method-assign]
    run_id = await queue_run(db.factory, tenant)
    result = await engine.run_sync(db.factory, sync_run_id=run_id, organization_id=tenant.org_id)

    assert result.status == "completed" and result.items_upserted == 2
    async with db.factory() as session:
        actions = await session.execute(
            select(AuditLog.action).where(AuditLog.organization_id == tenant.org_id)
        )
        assert "connector.sync.item.skipped" in set(actions.scalars())


@pytest.mark.asyncio
async def test_changed_items_are_rewritten_and_reingested(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    first = scale_adapter(tenant, 200, file_every=10)
    engine = make_engine(first, with_bridge=True)
    await engine.run_sync(
        db.factory, sync_run_id=await queue_run(db.factory, tenant), organization_id=tenant.org_id
    )
    engine = make_engine(scale_adapter(tenant, 200, file_every=10, version="v2"), with_bridge=True)
    run_id = await queue_run(db.factory, tenant, full=True)

    result = await engine.run_sync(db.factory, sync_run_id=run_id, organization_id=tenant.org_id)

    assert result.status == "completed" and result.items_upserted == 200
    async with db.factory() as session:
        hashes = await session.execute(
            select(ExternalItem.sync_version).where(
                ExternalItem.connection_id == tenant.connection_id
            )
        )
        run = await load_run_row(db.factory, run_id)
        assert set(hashes.scalars()) == {run.sync_version}
    assert len(await outbox_rows(db.factory, tenant)) == 2 * 20


@pytest.mark.asyncio
async def test_cancel_between_short_pages_is_seen_before_the_next_fetch(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 90)
    adapter.page_size_override = 30

    async def cancel_on_second(offset: int) -> None:
        if offset == 30:
            await cancel(db.factory, tenant, run_id)

    adapter.on_fetch = cancel_on_second
    run_id = await queue_run(db.factory, tenant)
    result = await make_engine(adapter).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id
    )

    assert result.status == "cancelled" and result.pages_committed == 2
    assert len(adapter.list_calls) == 2


@pytest.mark.asyncio
async def test_file_ingestion_skips_are_audited(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 30, file_every=10)

    async def download(**kwargs: Any) -> Any:
        provider_item_id = kwargs["provider_item_id"]
        if provider_item_id == item_id(0):
            raise RuntimeError("provider 500")
        if provider_item_id == item_id(10):
            return None
        return (b"hello", "page.txt", "text/plain")

    adapter.download_file_content = download  # type: ignore[method-assign]
    engine = make_engine(adapter, with_bridge=True)
    engine.ingestion_bridge.ingest_item = AsyncMock(side_effect=RuntimeError("bridge"))  # type: ignore[union-attr,method-assign]
    run_id = await queue_run(db.factory, tenant)
    result = await engine.run_sync(db.factory, sync_run_id=run_id, organization_id=tenant.org_id)
    assert result.status == "completed" and await outbox_rows(db.factory, tenant) == []

    async with db.factory() as session, session.begin():
        connection = await session.get(ConnectorConnection, tenant.connection_id)
        assert connection is not None
        connection.created_by_user_id = None
    adapter.download_file_content = AsyncMock(return_value=(b"x", "a.txt", "text/plain"))  # type: ignore[method-assign]
    await engine.run_sync(
        db.factory,
        sync_run_id=await queue_run(db.factory, tenant, full=True),
        organization_id=tenant.org_id,
    )

    async with db.factory() as session:
        rows = await session.execute(
            select(AuditLog.metadata_json).where(AuditLog.organization_id == tenant.org_id)
        )
        reasons = {m.get("reason") for m in rows.scalars() if isinstance(m, dict)}
    assert {
        "download_failed",
        "download_not_available",
        "bridge_error",
        "missing_uploader_user",
    } <= reasons


@pytest.mark.isolation
@pytest.mark.asyncio
async def test_items_naming_another_connection_are_skipped(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 10)
    original = adapter.make_item

    def other_connection(index: int) -> Any:
        item = original(index)
        return item.model_copy(update={"connection_id": uuid4()}) if index < 4 else item

    adapter.make_item = other_connection  # type: ignore[method-assign]
    run_id = await queue_run(db.factory, tenant)
    result = await make_engine(adapter).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id
    )
    assert result.items_upserted == 6 and await item_counts(db.factory, tenant) == (6, 0)


@pytest.mark.asyncio
async def test_items_without_a_connection_id_are_bound_to_the_run(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    adapter = scale_adapter(tenant, 5)
    adapter.connection_id = None
    run_id = await queue_run(db.factory, tenant)
    result = await make_engine(adapter).run_sync(
        db.factory, sync_run_id=run_id, organization_id=tenant.org_id
    )
    assert result.items_upserted == 5 and await item_counts(db.factory, tenant) == (5, 0)


async def _oauth(db: SqliteDb, tenant: Any, *, expires_at: datetime | None = None) -> None:
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
                expires_at=expires_at,
            )
        )


@pytest.mark.asyncio
async def test_failed_token_refresh_fails_the_run_as_auth_error(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    await _oauth(db, tenant)
    adapter = scale_adapter(tenant, PAGE)

    async def expired(offset: int) -> None:
        raise ConnectorAuthError("401")

    adapter.on_fetch = expired
    engine = make_engine(adapter)
    engine.credential_vault.decrypt = MagicMock(return_value={"token": "t"})  # type: ignore[method-assign]
    lifecycle = MagicMock()
    lifecycle.refresh_oauth_credential = AsyncMock(side_effect=RuntimeError("idp down"))
    engine._oauth_lifecycle = lifecycle
    run_id = await queue_run(db.factory, tenant)

    result = await engine.run_sync(db.factory, sync_run_id=run_id, organization_id=tenant.org_id)

    assert result.status == "failed"
    assert (await load_run_row(db.factory, run_id)).error_details_json["code"] == "auth_error"


@pytest.mark.asyncio
async def test_expiring_token_is_refreshed_before_the_first_page(db: SqliteDb) -> None:
    tenant = await _tenant(db)
    await _oauth(db, tenant, expires_at=datetime.now(UTC) + timedelta(seconds=5))
    engine = make_engine(scale_adapter(tenant, 10))
    engine.credential_vault.decrypt = MagicMock(return_value={"token": "t"})  # type: ignore[method-assign]
    lifecycle = MagicMock()
    lifecycle.refresh_oauth_credential = AsyncMock()
    engine._oauth_lifecycle = lifecycle
    run_id = await queue_run(db.factory, tenant)

    result = await engine.run_sync(db.factory, sync_run_id=run_id, organization_id=tenant.org_id)

    assert result.status == "completed"
    lifecycle.refresh_oauth_credential.assert_awaited_once()
