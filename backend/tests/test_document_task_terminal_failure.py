"""Terminal failure must preserve deletion/security statuses (R02-02b)."""

from __future__ import annotations

import os
from decimal import Decimal
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

from vector_fake_support import PointLedgerMixin

from app.clients import minio_client as minio_module
from app.core.config import settings
from app.domains.documents.repositories.processing_claims import (
    NON_PROCESSABLE_STATUSES,
    PROCESS_SKIP_STATUSES,
    REINDEX_FORBIDDEN_STATUSES,
    TERMINAL_FAILURE_PROTECTED_STATUSES,
)
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User
from app.workers import document_tasks, status_tracking
from app.workers.base_task import PermanentTaskError
from app.workers.status_tracking import FailureMarkOutcome, FailureMarkResult

PII_TEXT = (
    "IDs: 123-45-6789, 234-56-7890, 345-67-8901, 456-78-9012, 321-54-9876. "
    "Employees receive twenty days of annual leave."
)


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, amt: int | None = None) -> bytes:
        # Sized reads (R06-02): consume the data, then return b"".
        pos = getattr(self, "_pos", 0)
        end = len(self._data) if amt is None else pos + amt
        self._pos = end
        return self._data[pos:end]

    def close(self) -> None:
        return None


class _FakeMinio:
    def get_object(self, **_: Any) -> dict[str, Any]:
        return {"Body": _Body(PII_TEXT.encode())}


class _FakeEmbeddings:
    async def embed_chunks(self, *, chunks: list[Any]) -> Any:
        tokens = sum(int(getattr(chunk, "token_count", 0)) for chunk in chunks)
        return type(
            "R",
            (),
            {
                "model_name": settings.openai_embedding_model,
                "index_version": settings.document_index_version,
                "batch_count": 1,
                "retry_count": 0,
                "input_tokens": tokens,
                "total_tokens": tokens,
                "latency_ms": 1,
                "approximate_cost_usd": Decimal("0"),
                "vectors_by_chunk_id": {
                    chunk.id: [0.001] * settings.qdrant_vector_size for chunk in chunks
                },
            },
        )()


class _FakeQdrant(PointLedgerMixin):
    @staticmethod
    def build_point_id(*, document_id: Any, chunk_index: int, index_version: str) -> str:
        return f"{document_id}:{index_version}:{chunk_index}"

    async def upsert_chunks(self, *, chunks: list[Any], **_: Any) -> Any:
        return type("R", (), {"upserted_count": len(chunks), "batch_count": 1})()

    async def delete_document_points(self, **_: Any) -> Any:
        return type("R", (), {"deleted": True})()


@pytest_asyncio.fixture
async def make_document(db_session: AsyncSession) -> Any:
    org = Organization(name="Failure Org", slug=f"failure-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"failure-user-{uuid4().hex[:8]}",
        email=f"failure-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    async def _make(status: str, *, task_id: str | None = None) -> Document:
        document = Document(
            organization_id=org.id,
            uploaded_by_user_id=user.id,
            filename="failure.txt",
            file_type="txt",
            storage_bucket="documents",
            storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
            status=status,
            processing_task_id=task_id,
        )
        db_session.add(document)
        await db_session.commit()
        return document

    return _make


@pytest.fixture
def session_factory(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> async_sessionmaker[AsyncSession]:
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(status_tracking, "SessionLocal", factory)
    monkeypatch.setattr(document_tasks, "SessionLocal", factory)
    return factory


async def _mark(document: Document, *, owner: str | None = "task-a") -> FailureMarkResult:
    return await status_tracking._mark_document_failed_async(
        str(document.id),
        error_message="boom",
        owner_task_id=owner,
        protected_statuses=TERMINAL_FAILURE_PROTECTED_STATUSES,
    )


def test_status_sets() -> None:
    assert DocumentStatus.deleted.value in TERMINAL_FAILURE_PROTECTED_STATUSES
    assert NON_PROCESSABLE_STATUSES < TERMINAL_FAILURE_PROTECTED_STATUSES
    assert NON_PROCESSABLE_STATUSES < PROCESS_SKIP_STATUSES
    assert DocumentStatus.indexed.value in PROCESS_SKIP_STATUSES
    assert DocumentStatus.failed.value not in PROCESS_SKIP_STATUSES


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(TERMINAL_FAILURE_PROTECTED_STATUSES))
async def test_protected_status_survives_terminal_failure(
    db_session: AsyncSession,
    make_document: Any,
    session_factory: async_sessionmaker[AsyncSession],
    status: str,
) -> None:
    document = await make_document(status, task_id="task-a")
    result = await _mark(document)

    assert result.outcome == FailureMarkOutcome.protected
    assert result.current_status == status
    await db_session.refresh(document)
    assert document.status == status
    assert document.error_message is None
    assert document.processing_task_id is None


@pytest.mark.asyncio
async def test_protected_status_keeps_foreign_claim_columns(
    db_session: AsyncSession,
    make_document: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await make_document(DocumentStatus.deleting.value, task_id=None)
    result = await _mark(document)
    assert result.outcome == FailureMarkOutcome.protected
    await db_session.refresh(document)
    assert document.status == DocumentStatus.deleting.value


@pytest.mark.asyncio
async def test_ordinary_failure_marks_failed(
    db_session: AsyncSession,
    make_document: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await make_document(DocumentStatus.processing.value, task_id="task-a")
    result = await _mark(document)

    assert result.outcome == FailureMarkOutcome.updated
    await db_session.refresh(document)
    assert document.status == DocumentStatus.failed.value
    assert document.error_message == "boom"
    assert document.processing_task_id is None


@pytest.mark.asyncio
async def test_superseded_and_missing_documents(
    db_session: AsyncSession,
    make_document: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await make_document(DocumentStatus.processing.value, task_id="task-new")
    result = await _mark(document, owner="task-old")
    assert result.outcome == FailureMarkOutcome.superseded
    await db_session.refresh(document)
    assert document.status == DocumentStatus.processing.value
    assert document.processing_task_id == "task-new"

    missing = await status_tracking._mark_document_failed_async(
        str(uuid4()),
        error_message="boom",
        owner_task_id="task-a",
        protected_statuses=TERMINAL_FAILURE_PROTECTED_STATUSES,
    )
    assert missing.outcome == FailureMarkOutcome.not_found


def test_sync_wrapper_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(document_id: str, **kwargs: Any) -> FailureMarkResult:
        return FailureMarkResult(FailureMarkOutcome.updated, document_id)

    monkeypatch.setattr(status_tracking, "_mark_document_failed_async", _fake)
    monkeypatch.setattr(status_tracking, "_run", lambda coro: _drive(coro))
    result = status_tracking.mark_document_failed(
        "doc-1", error_message=None, owner_task_id=None, protected_statuses=()
    )
    assert result == FailureMarkResult(FailureMarkOutcome.updated, "doc-1")


def _drive(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("coroutine did not finish")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [DocumentStatus.deleted.value, DocumentStatus.deleting.value])
async def test_reindex_of_deleted_document_raises_and_status_is_preserved(
    db_session: AsyncSession,
    make_document: Any,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    document = await make_document(status)
    claim = await status_tracking._claim_document_for_processing_async(
        str(document.id),
        task_id="task-a",
        force=False,
        forbidden_statuses=REINDEX_FORBIDDEN_STATUSES,
    )
    monkeypatch.setattr(document_tasks, "claim_document_for_processing", lambda *a, **k: claim)

    with pytest.raises(PermanentTaskError):
        document_tasks.reindex_document.run(str(document.id))

    result = await _mark(document, owner="task-a")
    assert result.outcome == FailureMarkOutcome.protected
    await db_session.refresh(document)
    assert document.status == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "expected"),
    [("quarantine", DocumentStatus.quarantined), ("reject", DocumentStatus.blocked)],
)
async def test_dlp_quarantine_and_reject_survive_terminal_failure(
    db_session: AsyncSession,
    make_document: Any,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    expected: DocumentStatus,
) -> None:
    document = await make_document(DocumentStatus.processing.value, task_id="task-a")
    monkeypatch.setattr(minio_module, "minio_client", _FakeMinio())
    monkeypatch.setattr(document_tasks, "_embedding_service", _FakeEmbeddings())
    monkeypatch.setattr(document_tasks, "_qdrant_service", _FakeQdrant())
    monkeypatch.setattr(settings, "dlp_enabled", True)
    monkeypatch.setattr(settings, "dlp_action", action)

    with pytest.raises(document_tasks.DocumentPipelinePermanentError):
        await document_tasks._extract_and_store_document_pages_async(str(document.id))
    await db_session.refresh(document)
    assert document.status == expected.value

    result = await _mark(document, owner="task-a")
    assert result.outcome == FailureMarkOutcome.protected
    await db_session.refresh(document)
    assert document.status == expected.value
    assert document.processing_task_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("persist_document_state", [False, True])
async def test_dlp_warn_respects_persist_document_state(
    db_session: AsyncSession,
    make_document: Any,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    persist_document_state: bool,
) -> None:
    document = await make_document(DocumentStatus.indexed.value)
    monkeypatch.setattr(minio_module, "minio_client", _FakeMinio())
    monkeypatch.setattr(document_tasks, "_embedding_service", _FakeEmbeddings())
    monkeypatch.setattr(document_tasks, "_qdrant_service", _FakeQdrant())
    monkeypatch.setattr(settings, "dlp_enabled", True)
    monkeypatch.setattr(settings, "dlp_action", "warn")

    async def _no_graph(*_: Any, **__: Any) -> dict[str, int]:
        return {"entity_count": 0, "relation_count": 0}

    monkeypatch.setattr(document_tasks, "_run_document_graph_extraction_async", _no_graph)
    index_version = None if persist_document_state else "eval-dlp-warn"
    await document_tasks._extract_and_store_document_pages_async(
        str(document.id),
        chunking_service=document_tasks._make_chunking_service(
            {"strategy": "token_recursive"}, index_version=index_version
        ),
        persist_document_state=persist_document_state,
    )

    await db_session.refresh(document)
    assert document.status == DocumentStatus.indexed.value
    if persist_document_state:
        assert document.dlp_scan_result is not None
        assert document.dlp_scan_result["action"] == "warn"
    else:
        assert document.dlp_scan_result is None


def _failure_kwargs() -> dict[str, Any]:
    return {"organization_id": str(uuid4()), "user_id": str(uuid4())}


@pytest.mark.parametrize(
    ("status", "notifies"),
    [
        (DocumentStatus.quarantined.value, True),
        (DocumentStatus.blocked.value, True),
        (DocumentStatus.deleted.value, False),
        (DocumentStatus.deleting.value, False),
        (DocumentStatus.delete_requested.value, False),
        (DocumentStatus.retained_by_policy.value, False),
    ],
)
def test_on_terminal_failure_preserves_protected_status(
    monkeypatch: pytest.MonkeyPatch, status: str, notifies: bool
) -> None:
    from app.workers import email_helper, notification_helper

    events: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []
    emails: list[dict[str, Any]] = []
    monkeypatch.setattr(
        document_tasks,
        "mark_document_failed",
        lambda *a, **k: FailureMarkResult(FailureMarkOutcome.protected, status),
    )
    monkeypatch.setattr(document_tasks, "log_document_event", lambda **kw: events.append(kw))
    monkeypatch.setattr(document_tasks, "_record_worker_audit", lambda **kw: audits.append(kw))
    monkeypatch.setattr(
        notification_helper, "emit_notification", lambda **kw: notifications.append(kw)
    )
    monkeypatch.setattr(email_helper, "emit_upload_failure_email", lambda **kw: emails.append(kw))

    document_tasks.process_document.on_terminal_failure(
        exc=RuntimeError("boom"), args=("doc-1",), kwargs=_failure_kwargs()
    )

    assert [e["event"] for e in events] == ["document.processing.failure_status_preserved"]
    assert events[0]["current_status"] == status
    assert [a["action"] for a in audits] == ["document.task.failure_ignored"]
    assert audits[0]["metadata"]["status"] == status
    assert len(notifications) == (1 if notifies else 0)
    assert emails == []


def test_on_terminal_failure_ordinary_failure_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import email_helper, notification_helper

    audits: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []
    emails: list[dict[str, Any]] = []
    monkeypatch.setattr(
        document_tasks,
        "mark_document_failed",
        lambda *a, **k: FailureMarkResult(FailureMarkOutcome.updated, "failed"),
    )
    monkeypatch.setattr(document_tasks, "log_document_event", lambda **kw: None)
    monkeypatch.setattr(document_tasks, "_record_worker_audit", lambda **kw: audits.append(kw))
    monkeypatch.setattr(
        notification_helper, "emit_notification", lambda **kw: notifications.append(kw)
    )
    monkeypatch.setattr(email_helper, "emit_upload_failure_email", lambda **kw: emails.append(kw))

    document_tasks.process_document.on_terminal_failure(
        exc=RuntimeError("boom"), args=("doc-1",), kwargs=_failure_kwargs()
    )

    assert [a["action"] for a in audits] == ["document.task.failed"]
    assert len(notifications) == 1
    assert len(emails) == 1


def test_on_terminal_failure_not_found_returns_early(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        document_tasks,
        "mark_document_failed",
        lambda *a, **k: FailureMarkResult(FailureMarkOutcome.not_found),
    )
    monkeypatch.setattr(
        document_tasks, "log_document_event", lambda **kw: events.append(kw["event"])
    )
    document_tasks.process_document.on_terminal_failure(
        exc=RuntimeError("boom"), args=("doc-1",), kwargs={}
    )
    assert events == ["document.processing.failure_superseded"]
