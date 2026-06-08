"""Tests for F240: connector sync engine, job lifecycle, retries, and scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.connectors.schemas.connectors import (
    NormalizedExternalItem,
)
from app.domains.connectors.services.connector_service import ConnectorPlatformService
from app.domains.connectors.services.provider_adapter import (
    ConnectorAdapterNotFoundError,
    ConnectorAuthError,
    ConnectorContentError,
    ConnectorIngestionError,
    ConnectorPermissionError,
    ConnectorProviderAdapter,
    ConnectorProviderUnavailableError,
    ConnectorRateLimitError,
    DeltaItem,
    DeltaPage,
    ItemPage,
    SyncAdapterRegistry,
)
from app.domains.connectors.services.sync_engine import (
    ConnectorSyncEngine,
    SyncEngineError,
    _next_run_due,
)
from app.models.connector import ConnectorConnection, ConnectorProvider
from app.models.connector_sync import ConnectorSyncJob
from app.models.enums import ConnectorSyncJobStatus, ConnectorSyncRunStatus
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

HASH_A = "a" * 64
HASH_B = "b" * 64


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class SyncContext:
    org_id: UUID
    user_id: UUID
    connection: ConnectorConnection
    provider: ConnectorProvider


async def _create_sync_context(db_session: AsyncSession) -> SyncContext:
    org = Organization(name=f"SyncOrg {uuid4()}", slug=f"sync-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"sync-user-{uuid4()}",
        email=f"sync-{uuid4().hex[:8]}@example.test",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role="admin",
        )
    )
    await db_session.flush()

    service = ConnectorPlatformService()
    connection = await service.create_connection(
        db_session,
        organization_id=org.id,
        provider_key="confluence",
        display_name="Confluence Connection",
        created_by_user_id=user.id,
    )
    await db_session.flush()

    return SyncContext(
        org_id=org.id,
        user_id=user.id,
        connection=connection,
        provider=connection.provider,
    )


class StubAdapter(ConnectorProviderAdapter):
    """Stub adapter that returns a configurable set of items."""

    def __init__(
        self,
        items: list[NormalizedExternalItem] | None = None,
        delta_items: list[DeltaItem] | None = None,
        raise_on_call: Exception | None = None,
    ) -> None:
        self.items = items or []
        self.delta_items = delta_items or []
        self.raise_on_call = raise_on_call
        self.list_items_calls: int = 0
        self.delta_sync_calls: int = 0

    async def list_items(self, **kwargs: Any) -> ItemPage:
        self.list_items_calls += 1
        if self.raise_on_call:
            raise self.raise_on_call
        return ItemPage(items=self.items, has_more=False)

    async def delta_sync(self, **kwargs: Any) -> DeltaPage:
        self.delta_sync_calls += 1
        if self.raise_on_call:
            raise self.raise_on_call
        return DeltaPage(items=self.delta_items, has_more=False)


def _make_registry(adapter: ConnectorProviderAdapter) -> SyncAdapterRegistry:
    reg = SyncAdapterRegistry()
    reg.register("test_provider", adapter)
    return reg


def _engine_with_adapter(adapter: ConnectorProviderAdapter) -> ConnectorSyncEngine:
    return ConnectorSyncEngine(adapter_registry=_make_registry(adapter))


def _norm_item(
    org_id: UUID,
    connection_id: UUID,
    *,
    provider_item_id: str = "item-1",
    content_hash: str = HASH_A,
    sync_version: int = 1,
) -> NormalizedExternalItem:
    return NormalizedExternalItem(
        organization_id=org_id,
        provider_key="test_provider",
        provider_item_id=provider_item_id,
        item_type="cloud_file",
        title="Test Item",
        source_url="https://example.test/item-1",
        content_hash=content_hash,
        updated_at=datetime.now(UTC),
        sync_version=sync_version,
        connection_id=connection_id,
    )


# ---------------------------------------------------------------------------
# Error class tests
# ---------------------------------------------------------------------------


def test_connector_auth_error_is_permanent() -> None:
    from app.workers.base_task import PermanentTaskError

    err = ConnectorAuthError("token expired")
    assert isinstance(err, PermanentTaskError)


def test_connector_rate_limit_error_is_transient_with_default_delay() -> None:
    from app.workers.base_task import TransientTaskError

    err = ConnectorRateLimitError("429 Too Many Requests")
    assert isinstance(err, TransientTaskError)
    assert err.retry_after_seconds == 60


def test_connector_rate_limit_error_accepts_custom_delay() -> None:
    err = ConnectorRateLimitError("429", retry_after_seconds=120)
    assert err.retry_after_seconds == 120


def test_connector_provider_unavailable_is_transient() -> None:
    from app.workers.base_task import TransientTaskError

    assert isinstance(ConnectorProviderUnavailableError("down"), TransientTaskError)


def test_connector_permission_error_is_permanent() -> None:
    from app.workers.base_task import PermanentTaskError

    assert isinstance(ConnectorPermissionError("forbidden"), PermanentTaskError)


def test_connector_content_error_is_permanent() -> None:
    from app.workers.base_task import PermanentTaskError

    assert isinstance(ConnectorContentError("unreadable"), PermanentTaskError)


def test_connector_ingestion_error_is_transient() -> None:
    from app.workers.base_task import TransientTaskError

    assert isinstance(ConnectorIngestionError("retry"), TransientTaskError)


# ---------------------------------------------------------------------------
# SyncAdapterRegistry tests
# ---------------------------------------------------------------------------


def test_adapter_registry_register_and_get() -> None:
    reg = SyncAdapterRegistry()
    adapter = StubAdapter()
    reg.register("confluence", adapter)
    assert reg.get("confluence") is adapter
    assert reg.get("CONFLUENCE") is adapter  # case-insensitive


def test_adapter_registry_require_raises_if_missing() -> None:
    reg = SyncAdapterRegistry()
    with pytest.raises(ConnectorAdapterNotFoundError):
        reg.require("missing_provider")


def test_adapter_registry_require_returns_adapter() -> None:
    reg = SyncAdapterRegistry()
    adapter = StubAdapter()
    reg.register("test", adapter)
    assert reg.require("test") is adapter


# ---------------------------------------------------------------------------
# Schedule due-check tests
# ---------------------------------------------------------------------------


def test_next_run_due_returns_true_when_no_last_run() -> None:
    job = ConnectorSyncJob(
        organization_id=uuid4(),
        connection_id=uuid4(),
        name="test",
        status="active",
        schedule_json={"type": "interval", "interval_minutes": 60},
        cursor_json={},
        last_run_at=None,
    )
    assert _next_run_due(job, datetime.now(UTC)) is True


def test_next_run_due_returns_false_before_interval() -> None:
    now = datetime.now(UTC)
    job = ConnectorSyncJob(
        organization_id=uuid4(),
        connection_id=uuid4(),
        name="test",
        status="active",
        schedule_json={"type": "interval", "interval_minutes": 60},
        cursor_json={},
        last_run_at=now - timedelta(minutes=30),
    )
    assert _next_run_due(job, now) is False


def test_next_run_due_returns_true_after_interval() -> None:
    now = datetime.now(UTC)
    job = ConnectorSyncJob(
        organization_id=uuid4(),
        connection_id=uuid4(),
        name="test",
        status="active",
        schedule_json={"type": "interval", "interval_minutes": 60},
        cursor_json={},
        last_run_at=now - timedelta(minutes=61),
    )
    assert _next_run_due(job, now) is True


def test_next_run_due_manual_only_never_due() -> None:
    job = ConnectorSyncJob(
        organization_id=uuid4(),
        connection_id=uuid4(),
        name="test",
        status="active",
        schedule_json={"type": "manual_only"},
        cursor_json={},
        last_run_at=None,
    )
    assert _next_run_due(job, datetime.now(UTC)) is False


# ---------------------------------------------------------------------------
# Sync engine: job management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_sync_job_returns_active_job(db_session: AsyncSession) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()

    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="Hourly sync",
        schedule={"type": "interval", "interval_minutes": 60},
    )

    assert job.name == "Hourly sync"
    assert job.status == ConnectorSyncJobStatus.active.value
    assert job.organization_id == ctx.org_id
    assert job.connection_id == ctx.connection.id
    assert job.schedule_json == {"type": "interval", "interval_minutes": 60}


@pytest.mark.asyncio
async def test_create_sync_job_raises_for_unknown_connection(
    db_session: AsyncSession,
) -> None:
    engine = ConnectorSyncEngine()
    with pytest.raises(SyncEngineError, match="not found"):
        await engine.create_sync_job(
            db_session,
            organization_id=uuid4(),
            connection_id=uuid4(),
            name="job",
        )


@pytest.mark.asyncio
async def test_update_sync_job_status_pauses_job(db_session: AsyncSession) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()
    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job",
    )

    updated = await engine.update_sync_job_status(
        db_session,
        organization_id=ctx.org_id,
        job_id=job.id,
        status=ConnectorSyncJobStatus.paused,
    )
    assert updated.status == ConnectorSyncJobStatus.paused.value


@pytest.mark.asyncio
async def test_list_sync_jobs_returns_jobs_for_connection(
    db_session: AsyncSession,
) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()
    await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job-1",
    )
    await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job-2",
    )

    jobs = await engine.list_sync_jobs(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
    )
    assert len(jobs) == 2
    names = {j.name for j in jobs}
    assert names == {"job-1", "job-2"}


# ---------------------------------------------------------------------------
# Sync engine: run management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_manual_sync_creates_queued_run(db_session: AsyncSession) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()
    await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job",
    )

    run = await engine.trigger_manual_sync(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
    )

    assert run.status == ConnectorSyncRunStatus.queued.value
    assert run.trigger_type == "manual"
    assert run.organization_id == ctx.org_id


@pytest.mark.asyncio
async def test_trigger_manual_sync_blocks_concurrent_run(
    db_session: AsyncSession,
) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()
    await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job",
    )
    # First trigger succeeds
    await engine.trigger_manual_sync(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
    )
    # Second trigger raises
    with pytest.raises(SyncEngineError, match="already queued or running"):
        await engine.trigger_manual_sync(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )


@pytest.mark.asyncio
async def test_cancel_run_marks_run_cancelled(db_session: AsyncSession) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()
    await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job",
    )
    run = await engine.trigger_manual_sync(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
    )

    cancelled = await engine.cancel_run(db_session, organization_id=ctx.org_id, run_id=run.id)
    assert cancelled.status == ConnectorSyncRunStatus.cancelled.value
    assert cancelled.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_run_rejects_completed_run(db_session: AsyncSession) -> None:
    ctx = await _create_sync_context(db_session)
    engine = _engine_with_adapter(StubAdapter(items=[]))
    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job",
    )
    run = await engine.trigger_manual_sync(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        job_id=job.id,
    )
    # Run it to completion (no credential = fail, but still terminal)
    await engine.run_sync(db_session, sync_run_id=run.id, organization_id=ctx.org_id)
    await db_session.flush()

    completed_run = await engine.get_sync_run(db_session, organization_id=ctx.org_id, run_id=run.id)
    assert completed_run is not None
    assert completed_run.status in {"completed", "failed"}

    with pytest.raises(SyncEngineError, match="terminal state"):
        await engine.cancel_run(db_session, organization_id=ctx.org_id, run_id=run.id)


# ---------------------------------------------------------------------------
# Sync engine: dispatch_due_syncs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_due_syncs_returns_overdue_jobs(
    db_session: AsyncSession,
) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()
    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="due job",
        schedule={"type": "interval", "interval_minutes": 60},
    )
    # Simulate last run 2 hours ago
    job.last_run_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.flush()

    dispatched = await engine.dispatch_due_syncs(db_session)
    assert len(dispatched) == 1
    assert dispatched[0][1] == ctx.org_id


@pytest.mark.asyncio
async def test_dispatch_due_syncs_skips_paused_job(db_session: AsyncSession) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()
    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="paused",
        schedule={"type": "interval", "interval_minutes": 60},
    )
    job.status = ConnectorSyncJobStatus.paused.value
    await db_session.flush()

    dispatched = await engine.dispatch_due_syncs(db_session)
    assert dispatched == []


@pytest.mark.asyncio
async def test_dispatch_due_syncs_skips_job_with_active_run(
    db_session: AsyncSession,
) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine()
    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="busy",
        schedule={"type": "interval", "interval_minutes": 5},
    )
    await engine.trigger_manual_sync(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        job_id=job.id,
    )

    dispatched = await engine.dispatch_due_syncs(db_session)
    # Should be empty because a run is already queued
    assert len(dispatched) == 0


# ---------------------------------------------------------------------------
# Sync engine: run execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_sync_fails_gracefully_when_no_credential(
    db_session: AsyncSession,
) -> None:
    ctx = await _create_sync_context(db_session)
    engine = _engine_with_adapter(StubAdapter())
    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job",
    )
    run = await engine.trigger_manual_sync(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        job_id=job.id,
    )

    result = await engine.run_sync(db_session, sync_run_id=run.id, organization_id=ctx.org_id)

    assert result.status == "failed"
    assert "credential" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_run_sync_fails_when_adapter_not_registered(
    db_session: AsyncSession,
) -> None:
    ctx = await _create_sync_context(db_session)
    engine = ConnectorSyncEngine(adapter_registry=SyncAdapterRegistry())  # empty registry
    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job",
    )
    run = await engine.trigger_manual_sync(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        job_id=job.id,
    )

    # Add a fake credential so we reach adapter lookup
    from unittest.mock import MagicMock

    from app.models.connector_credential import ConnectorCredential

    cred = ConnectorCredential(
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        auth_type="api_token",
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
    db_session.add(cred)
    await db_session.flush()

    engine.credential_vault.decrypt = MagicMock(
        return_value={"provider_key": "confluence"}
    )

    result = await engine.run_sync(db_session, sync_run_id=run.id, organization_id=ctx.org_id)
    assert result.status == "failed"
    assert "adapter" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_run_sync_returns_cancelled_for_pre_cancelled_run(
    db_session: AsyncSession,
) -> None:
    ctx = await _create_sync_context(db_session)
    engine = _engine_with_adapter(StubAdapter())
    job = await engine.create_sync_job(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        name="job",
    )
    run = await engine.trigger_manual_sync(
        db_session,
        organization_id=ctx.org_id,
        connection_id=ctx.connection.id,
        job_id=job.id,
    )
    await engine.cancel_run(db_session, organization_id=ctx.org_id, run_id=run.id)

    result = await engine.run_sync(db_session, sync_run_id=run.id, organization_id=ctx.org_id)
    assert result.status == "cancelled"


# ---------------------------------------------------------------------------
# Ingestion bridge → process_document task dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_ingest_file_item_dispatches_process_document_task() -> None:
    """Pending-scan results should return the document and uploader ids."""
    from unittest.mock import AsyncMock, MagicMock

    from app.domains.connectors.services.ingestion_bridge import IngestionResult
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine
    from app.models.enums import DocumentStatus, ExternalItemType

    org_id = uuid4()
    user_id = uuid4()
    doc_id = uuid4()
    ext_item_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = uuid4()
    mock_run.organization_id = org_id
    mock_run.connection_id = uuid4()
    mock_run.sync_version = 1000

    mock_connection = MagicMock()
    mock_connection.id = mock_run.connection_id
    mock_connection.created_by_user_id = user_id

    mock_norm_item = MagicMock()
    mock_norm_item.item_type = ExternalItemType.cloud_file
    mock_norm_item.provider_item_id = "gdrive-file-1"
    mock_norm_item.mime_type = "application/pdf"
    mock_norm_item.source_url = "https://drive.google.com/file/d/abc123"
    mock_norm_item.title = "Test Doc"
    mock_norm_item.metadata = {}
    mock_norm_item.permissions = []
    mock_norm_item.visibility = MagicMock(value="org_wide")
    mock_norm_item.content_hash = "a" * 64
    mock_norm_item.sync_version = 1000

    mock_adapter = MagicMock()
    mock_adapter.download_file_content = AsyncMock(
        return_value=(b"%PDF-1.4 fake pdf", "test.pdf", "application/pdf")
    )

    mock_bridge = MagicMock()
    mock_bridge.ingest_item = AsyncMock(
        return_value=IngestionResult(
            document_id=doc_id,
            source_document_id=uuid4(),
            status=DocumentStatus.pending_scan,
            checksum="a" * 64,
            is_duplicate=False,
            duplicate_of_document_id=None,
            error=None,
        )
    )

    mock_ext_item = MagicMock()
    mock_ext_item.id = ext_item_id
    mock_ext_item.collection_id = None

    mock_session = AsyncMock()
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_ext_item
    mock_session.execute = AsyncMock(return_value=mock_execute_result)

    engine = ConnectorSyncEngine()
    engine.ingestion_bridge = mock_bridge

    result = await engine._maybe_ingest_file_item(
        mock_session,
        run=mock_run,
        connection=mock_connection,
        adapter=mock_adapter,
        norm_item=mock_norm_item,
        decrypted_credential={},
    )

    mock_bridge.ingest_item.assert_awaited_once()
    assert result == (
        str(doc_id),
        str(user_id),
    )


@pytest.mark.asyncio
async def test_maybe_ingest_file_item_does_not_dispatch_on_skipped_result() -> None:
    """Skipped ingestion results should return no follow-up work."""
    from unittest.mock import AsyncMock, MagicMock

    from app.domains.connectors.services.ingestion_bridge import IngestionResult
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine
    from app.models.enums import DocumentStatus, ExternalItemType

    org_id = uuid4()
    user_id = uuid4()
    existing_doc_id = uuid4()

    mock_run = MagicMock()
    mock_run.id = uuid4()
    mock_run.organization_id = org_id
    mock_run.connection_id = uuid4()
    mock_run.sync_version = 1000

    mock_connection = MagicMock()
    mock_connection.id = mock_run.connection_id
    mock_connection.created_by_user_id = user_id

    mock_norm_item = MagicMock()
    mock_norm_item.item_type = ExternalItemType.cloud_file
    mock_norm_item.provider_item_id = "gdrive-dup-1"
    mock_norm_item.mime_type = "application/pdf"
    mock_norm_item.source_url = "https://drive.google.com/file/d/dup"
    mock_norm_item.title = "Dup Doc"
    mock_norm_item.metadata = {}
    mock_norm_item.permissions = []
    mock_norm_item.visibility = MagicMock(value="org_wide")
    mock_norm_item.content_hash = "b" * 64
    mock_norm_item.sync_version = 1000

    mock_adapter = MagicMock()
    mock_adapter.download_file_content = AsyncMock(
        return_value=(b"%PDF-1.4 dup", "dup.pdf", "application/pdf")
    )

    mock_bridge = MagicMock()
    mock_bridge.ingest_item = AsyncMock(
        return_value=IngestionResult(
            document_id=existing_doc_id,
            source_document_id=uuid4(),
            status=DocumentStatus.skipped,
            checksum="b" * 64,
            is_duplicate=True,
            duplicate_of_document_id=existing_doc_id,
            error=None,
        )
    )

    mock_ext_item = MagicMock()
    mock_ext_item.id = uuid4()
    mock_ext_item.collection_id = None

    mock_session = AsyncMock()
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_ext_item
    mock_session.execute = AsyncMock(return_value=mock_execute_result)

    engine = ConnectorSyncEngine()
    engine.ingestion_bridge = mock_bridge

    result = await engine._maybe_ingest_file_item(
        mock_session,
        run=mock_run,
        connection=mock_connection,
        adapter=mock_adapter,
        norm_item=mock_norm_item,
        decrypted_credential={},
    )

    assert result is None
