from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.core import metrics
from app.core.config import settings
from app.core.document_errors import decode_document_error
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User
from app.workers import document_reaper_tasks, notification_helper
from app.workers.celery_app import celery_app

MakeDocument = Callable[..., Awaitable[Document]]


def _ago(seconds: int) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


@pytest.fixture
def sent(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )

    @asynccontextmanager
    async def _maintenance_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            session.info["rls_maintenance"] = True
            yield session

    monkeypatch.setattr(document_reaper_tasks, "maintenance_session", _maintenance_session)
    calls: list[dict[str, Any]] = []

    def _send_task(name: str, *, args: list[Any], kwargs: dict[str, Any]) -> None:
        calls.append({"name": name, "args": args, "kwargs": kwargs})

    monkeypatch.setattr(celery_app, "send_task", _send_task)
    return calls


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        notification_helper, "emit_notification", lambda **kwargs: captured.append(kwargs)
    )
    return captured


@pytest_asyncio.fixture
async def make_document(db_session: AsyncSession) -> MakeDocument:
    org = Organization(name="Reaper Org", slug=f"reaper-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"reaper-user-{uuid4().hex[:8]}",
        email=f"reaper-{uuid4().hex[:8]}@example.com",
        display_name="Reaper User",
    )
    db_session.add(user)
    await db_session.flush()

    async def _make(
        status: str = DocumentStatus.processing.value,
        *,
        task_id: str | None = "task-a",
        started_at: datetime | None = None,
        updated_at: datetime | None = None,
        reap_count: int = 0,
    ) -> Document:
        document = Document(
            organization_id=org.id,
            uploaded_by_user_id=user.id,
            filename="reaper.txt",
            file_type="txt",
            storage_bucket="documents",
            storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
            status=status,
            processing_task_id=task_id,
            processing_started_at=started_at,
            processing_reap_count=reap_count,
            updated_at=updated_at or datetime.now(UTC),
        )
        db_session.add(document)
        await db_session.commit()
        return document

    return _make


async def _reload(session: AsyncSession, document: Document) -> Document:
    await session.refresh(document)
    return document


@pytest.mark.asyncio
async def test_stale_document_is_requeued_exactly_once(
    db_session: AsyncSession,
    make_document: MakeDocument,
    sent: list[dict[str, Any]],
) -> None:
    stale = settings.document_processing_stale_seconds + 60
    document = await make_document(started_at=_ago(stale), updated_at=_ago(stale))

    result = await document_reaper_tasks._reap_stale_documents_async()

    assert result == {"requeued": 1, "failed": 0, "enqueue_errors": 0}
    assert sent == [
        {
            "name": "documents.process",
            "args": [str(document.id)],
            "kwargs": {
                "organization_id": str(document.organization_id),
                "user_id": str(document.uploaded_by_user_id),
            },
        }
    ]
    row = await _reload(db_session, document)
    assert row.status == DocumentStatus.processing.value
    assert row.processing_task_id is None
    assert row.processing_started_at is None
    assert row.processing_reap_count == 1

    second = await document_reaper_tasks._reap_stale_documents_async()
    assert second == {"requeued": 0, "failed": 0, "enqueue_errors": 0}
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_fresh_and_non_processing_documents_are_ignored(
    db_session: AsyncSession,
    make_document: MakeDocument,
    sent: list[dict[str, Any]],
) -> None:
    stale = settings.document_processing_stale_seconds + 60
    fresh = await make_document(started_at=_ago(30), updated_at=_ago(stale))
    others = [
        await make_document(status, task_id=None, updated_at=_ago(stale))
        for status in (
            DocumentStatus.uploaded.value,
            DocumentStatus.indexed.value,
            DocumentStatus.failed.value,
        )
    ]

    result = await document_reaper_tasks._reap_stale_documents_async()

    assert result == {"requeued": 0, "failed": 0, "enqueue_errors": 0}
    assert sent == []
    row = await _reload(db_session, fresh)
    assert row.processing_task_id == "task-a"
    for other in others:
        assert (await _reload(db_session, other)).processing_reap_count == 0


@pytest.mark.asyncio
async def test_legacy_processing_row_without_started_at_is_requeued(
    db_session: AsyncSession,
    make_document: MakeDocument,
    sent: list[dict[str, Any]],
) -> None:
    stale = settings.document_processing_stale_seconds + 60
    document = await make_document(task_id=None, started_at=None, updated_at=_ago(stale))

    result = await document_reaper_tasks._reap_stale_documents_async()

    assert result["requeued"] == 1
    assert [call["args"] for call in sent] == [[str(document.id)]]
    assert (await _reload(db_session, document)).processing_reap_count == 1


@pytest.mark.asyncio
async def test_exhausted_document_is_marked_failed(
    db_session: AsyncSession,
    make_document: MakeDocument,
    sent: list[dict[str, Any]],
    notifications: list[dict[str, Any]],
) -> None:
    stale = settings.document_processing_stale_seconds + 60
    document = await make_document(
        started_at=_ago(stale),
        updated_at=_ago(stale),
        reap_count=settings.document_reaper_max_attempts,
    )

    result = await document_reaper_tasks._reap_stale_documents_async()

    assert result == {"requeued": 0, "failed": 1, "enqueue_errors": 0}
    assert sent == []
    row = await _reload(db_session, document)
    assert row.status == DocumentStatus.failed.value
    assert row.processing_task_id is None
    assert row.processing_started_at is None
    assert row.processing_reap_count == 0
    _, details = decode_document_error(row.error_message)
    assert details is not None
    assert details["code"] == "PROCESSING_STALLED"
    assert details["retryable"] is True
    assert len(notifications) == 1
    assert notifications[0]["event_type"] == "upload_failed"
    assert notifications[0]["source_id"] == str(document.id)


@pytest.mark.asyncio
async def test_enqueue_failure_is_counted(
    db_session: AsyncSession,
    make_document: MakeDocument,
    sent: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = settings.document_processing_stale_seconds + 60
    document = await make_document(started_at=_ago(stale), updated_at=_ago(stale))

    def _broken_send(*_: Any, **__: Any) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr(celery_app, "send_task", _broken_send)

    result = await document_reaper_tasks._reap_stale_documents_async()

    assert result == {"requeued": 0, "failed": 0, "enqueue_errors": 1}
    # The row is released and its updated_at bumped, so it is retried after the next window.
    row = await _reload(db_session, document)
    assert row.processing_reap_count == 1
    assert row.processing_started_at is None


@pytest.mark.asyncio
async def test_mark_helpers_ignore_rows_that_left_processing(
    db_session: AsyncSession,
    make_document: MakeDocument,
) -> None:
    repo = document_reaper_tasks._claim_repository
    document = await make_document(DocumentStatus.indexed.value)
    now = datetime.now(UTC)

    assert await repo.mark_reaped(db_session, document_id=document.id, now=now) is False
    assert (
        await repo.mark_reap_exhausted(
            db_session, document_id=document.id, now=now, error_message="x"
        )
        is False
    )


def test_reap_task_runs_async_body(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake() -> dict[str, int]:
        return {"requeued": 2, "failed": 1, "enqueue_errors": 0}

    monkeypatch.setattr(document_reaper_tasks, "_reap_stale_documents_async", _fake)

    assert document_reaper_tasks.reap_stale_documents.run() == {
        "requeued": 2,
        "failed": 1,
        "enqueue_errors": 0,
    }


def test_reap_task_is_scheduled_and_routed() -> None:
    assert "documents.reap_stale" in celery_app.tasks
    entry = celery_app.conf.beat_schedule["documents-reap-stale"]
    assert entry["task"] == "documents.reap_stale"
    assert entry["schedule"] == settings.document_reaper_interval_seconds
    route = celery_app.conf.task_routes["documents.reap_stale"]
    assert route["queue"] == settings.celery_task_default_queue


def test_record_document_reaped_counts_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    before = metrics.registry.get_sample_value(
        "rudix_documents_reaped_total", {"outcome": "requeued"}
    )
    metrics.record_document_reaped("requeued")
    after = metrics.registry.get_sample_value(
        "rudix_documents_reaped_total", {"outcome": "requeued"}
    )
    assert (after or 0.0) == (before or 0.0) + 1.0

    monkeypatch.setattr(settings, "metrics_enabled", False)
    metrics.record_document_reaped("requeued")
    assert (
        metrics.registry.get_sample_value("rudix_documents_reaped_total", {"outcome": "requeued"})
        == after
    )
