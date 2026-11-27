"""Helpers for the R06-11 connector sync scale, resume, and poll tests.

``ScaleAdapter`` is a ``FakeProviderAdapter`` (F241) that generates its items lazily, so a
100,000-item source costs no memory up front, and calls ``on_fetch`` before returning each
page so a test can cancel, crash, or rate-limit at an exact page.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domains.connectors.schemas.connectors import (
    NormalizedExternalItem,
    ProviderCapabilities,
    ProviderRegistration,
)
from app.domains.connectors.sdk.content_hash import hash_text
from app.domains.connectors.sdk.testing import FakeProviderAdapter
from app.domains.connectors.services.connector_service import ConnectorPlatformService
from app.domains.connectors.services.ingestion_bridge import ConnectorIngestionBridge
from app.domains.connectors.services.provider_adapter import ItemPage, SyncAdapterRegistry
from app.domains.connectors.services.provider_registry import ProviderRegistry
from app.domains.connectors.services.sync_engine import ConnectorSyncEngine
from app.domains.documents.services.malware_scan import MalwareScanResult, MalwareScanService
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import ConnectorAuthType, ExternalItemType, ExternalItemVisibility
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.outbox import OutboxMessage
from app.models.user import User
from tests.conftest import _configure_sqlite_connection

PROVIDER_KEY = "scale_provider"
PAGE = 1000

OnFetch = Callable[[int], Awaitable[None]]


class WorkerKilled(BaseException):
    """Simulates a worker dying (SIGKILL, OOM): not an ``Exception``, nothing catches it."""


def item_id(index: int) -> str:
    return f"item-{index:06d}"


@dataclass
class ScaleAdapter(FakeProviderAdapter):
    """Pages of ``page_size_override`` items over ``total`` lazily generated items.

    Every ``file_every``-th item is a ``wiki_page`` (ingested as a document); the rest are
    ``issue`` items. ``skip`` leaves indexes out (deleted at the provider); ``foreign_org``
    stamps indexes with another organization (a misbehaving adapter).
    """

    total: int = 0
    organization_id: UUID | None = None
    connection_id: UUID | None = None
    file_every: int = 0
    skip: set[int] = field(default_factory=set)
    foreign_org: dict[int, UUID] = field(default_factory=dict)
    version: str = "v1"
    on_fetch: OnFetch | None = None
    on_download: Callable[[str], Awaitable[None]] | None = None

    def make_item(self, index: int) -> NormalizedExternalItem:
        is_file = bool(self.file_every) and index % self.file_every == 0
        org = self.foreign_org.get(index, self.organization_id)
        assert org is not None
        return NormalizedExternalItem(
            organization_id=org,
            provider_key=PROVIDER_KEY,
            provider_item_id=item_id(index),
            item_type=ExternalItemType.wiki_page if is_file else ExternalItemType.issue,
            title=f"Item {index}",
            source_url=f"https://scale.example.test/items/{index}",
            content_hash=hash_text(f"{self.version}:{index}"),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            sync_version=1,
            connection_id=self.connection_id,
            visibility=ExternalItemVisibility.org_wide,
        )

    async def list_items(self, **kwargs: Any) -> ItemPage:
        cursor = dict(kwargs["cursor"])
        self.list_calls.append({"cursor": cursor, "page_size": kwargs["page_size"]})
        offset = int(cursor.get("offset", 0))
        if self.on_fetch is not None:
            await self.on_fetch(offset)
        size = self.page_size_override or kwargs["page_size"]
        end = min(offset + size, self.total)
        items = [self.make_item(i) for i in range(offset, end) if i not in self.skip]
        has_more = end < self.total
        return ItemPage(
            items=items, next_cursor={"offset": end} if has_more else None, has_more=has_more
        )

    async def download_file_content(self, **kwargs: Any) -> tuple[bytes, str, str]:
        if self.on_download is not None:
            await self.on_download(kwargs["provider_item_id"])
        body = f"Plain text body {self.version} of {kwargs['provider_item_id']}.".encode()
        return body, "page.txt", "text/plain"


@dataclass
class Tenant:
    org_id: UUID
    user_id: UUID
    connection_id: UUID
    job_id: UUID


async def seed_tenant(session: AsyncSession, *, schedule: dict | None = None) -> Tenant:
    """Organization, admin user, connection (provider auth ``none``), and one sync job."""
    org = Organization(name=f"Scale {uuid4()}", slug=f"scale-{uuid4().hex[:10]}")
    session.add(org)
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"scale-{uuid4()}",
        email=f"scale-{uuid4().hex[:8]}@example.test",
    )
    session.add(user)
    await session.flush()
    session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="admin"))
    registry = ProviderRegistry()
    registry.register(
        ProviderRegistration(
            key=PROVIDER_KEY,
            display_name="Scale Provider",
            capabilities=ProviderCapabilities(auth_type=ConnectorAuthType.none),
        )
    )
    connection: ConnectorConnection = await ConnectorPlatformService(
        provider_registry=registry
    ).create_connection(
        session,
        organization_id=org.id,
        provider_key=PROVIDER_KEY,
        display_name="Scale Connection",
        created_by_user_id=user.id,
    )
    job = await ConnectorSyncEngine().create_sync_job(
        session,
        organization_id=org.id,
        connection_id=connection.id,
        name="scale job",
        schedule=schedule,
    )
    await session.flush()
    return Tenant(org_id=org.id, user_id=user.id, connection_id=connection.id, job_id=job.id)


def bridge() -> ConnectorIngestionBridge:
    scanner = MagicMock(spec=MalwareScanService)
    scanner.scan_bytes = AsyncMock(return_value=MalwareScanResult(status="clean", scanner="clamav"))
    return ConnectorIngestionBridge(malware_scan_service=scanner, duplicate_action="warn")


def make_engine(adapter: Any, *, with_bridge: bool = False) -> ConnectorSyncEngine:
    registry = SyncAdapterRegistry()
    registry.register(PROVIDER_KEY, adapter)
    engine = ConnectorSyncEngine(
        adapter_registry=registry, ingestion_bridge=bridge() if with_bridge else None
    )
    engine.sleep = AsyncMock()
    return engine


def scale_adapter(tenant: Tenant, total: int, **kwargs: Any) -> ScaleAdapter:
    return ScaleAdapter(
        total=total,
        organization_id=tenant.org_id,
        connection_id=tenant.connection_id,
        page_size_override=PAGE,
        **kwargs,
    )


async def queue_run(factory: Any, tenant: Tenant, *, full: bool = False) -> UUID:
    async with factory() as session, session.begin():
        engine = ConnectorSyncEngine()
        trigger = engine.trigger_full_resync if full else engine.trigger_manual_sync
        run = await trigger(
            session,
            organization_id=tenant.org_id,
            connection_id=tenant.connection_id,
            job_id=tenant.job_id,
        )
        return run.id


async def cancel(factory: Any, tenant: Tenant, run_id: UUID) -> None:
    async with factory() as session, session.begin():
        await ConnectorSyncEngine().cancel_run(
            session, organization_id=tenant.org_id, run_id=run_id
        )


async def load_run_row(factory: Any, run_id: UUID) -> ConnectorSyncRun:
    async with factory() as session:
        run = await session.get(ConnectorSyncRun, run_id)
        assert run is not None
        return run


async def load_job_row(factory: Any, job_id: UUID) -> ConnectorSyncJob:
    async with factory() as session:
        job = await session.get(ConnectorSyncJob, job_id)
        assert job is not None
        return job


async def count(factory: Any, model: Any, *where: Any) -> int:
    async with factory() as session:
        return int(
            (
                await session.execute(select(func.count()).select_from(model).where(*where))
            ).scalar_one()
        )


async def item_counts(factory: Any, tenant: Tenant) -> tuple[int, int]:
    """(live external items, tombstoned external items) of the tenant's connection."""
    live = await count(
        factory,
        ExternalItem,
        ExternalItem.connection_id == tenant.connection_id,
        ExternalItem.deleted_at.is_(None),
    )
    dead = await count(
        factory,
        ExternalItem,
        ExternalItem.connection_id == tenant.connection_id,
        ExternalItem.deleted_at.is_not(None),
    )
    return live, dead


async def outbox_rows(factory: Any, tenant: Tenant) -> list[OutboxMessage]:
    async with factory() as session:
        rows = await session.execute(
            select(OutboxMessage).where(OutboxMessage.organization_id == tenant.org_id)
        )
        return list(rows.scalars().all())


@dataclass
class SqliteDb:
    factory: async_sessionmaker[AsyncSession]
    path: Path


async def sqlite_factory(template: Path, tmp_dir: Path) -> AsyncIterator[SqliteDb]:
    """A file database where every session has its own connection (unlike ``db_session``)."""
    path = tmp_dir / "sync.db"
    shutil.copyfile(template, path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
    try:
        yield SqliteDb(async_sessionmaker(bind=engine, expire_on_commit=False), path)
    finally:
        await engine.dispose()
