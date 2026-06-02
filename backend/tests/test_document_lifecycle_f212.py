"""Unit and integration tests for F212: document lifecycle integration.

Covers:
- _make_chunking_service: default, custom profile, invalid config
- process_document / reindex_document accept chunking_profile_config
- chunk_count persisted on Document after indexing
- profile_source and extra fields written to chunking_config_snapshot
- chunking.started / chunking.completed events emitted
- backfill_documents dispatches reindex tasks for indexed documents
- backfill_documents raises PermanentTaskError for invalid org or profile
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

from app.clients import minio_client as minio_module
from app.core.config import settings
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.workers import document_tasks
from app.workers.base_task import PermanentTaskError
from app.workers.document_tasks import _make_chunking_service

# ---------------------------------------------------------------------------
# Shared fake infrastructure (mirrors test_document_processing_worker.py)
# ---------------------------------------------------------------------------


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        pass


class FakeMinioReader:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def get_object(self, **_: Any) -> dict[str, Any]:
        return {"Body": _Body(self.data)}


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def embed_chunks(self, *, chunks: list[Any]) -> Any:
        self.calls.append(chunks)
        input_tokens = sum(int(getattr(c, "token_count", 0)) for c in chunks)
        return type(
            "R",
            (),
            {
                "model_name": settings.openai_embedding_model,
                "index_version": settings.document_index_version,
                "batch_count": 1,
                "retry_count": 0,
                "input_tokens": input_tokens,
                "total_tokens": input_tokens,
                "latency_ms": 5,
                "approximate_cost_usd": Decimal("0.000001"),
                "vectors_by_chunk_id": {
                    c.id: [0.001] * settings.qdrant_vector_size for c in chunks
                },
            },
        )()


class FakeQdrantService:
    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    @staticmethod
    def build_point_id(*, document_id: UUID, chunk_index: int, index_version: str) -> str:
        return f"{document_id}:{index_version}:{chunk_index}"

    async def upsert_chunks(self, *, chunks: list[Any], **_: Any) -> Any:
        self.upsert_calls.append({"chunks": chunks})
        return type("R", (), {"upserted_count": len(chunks), "batch_count": 1})()

    async def delete_document_points(self, **_: Any) -> Any:
        self.delete_calls.append({})
        return type("R", (), {"deleted": True})()


# ---------------------------------------------------------------------------
# DB fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_document(db_session: AsyncSession) -> Document:
    org = Organization(name="F212 Org", slug=f"f212-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"f212-user-{uuid4().hex[:8]}",
        email=f"f212-{uuid4().hex[:8]}@example.com",
        display_name="F212 User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=OrganizationRole.member.value
        )
    )
    await db_session.flush()

    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="f212.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{user.id}/{uuid4()}.txt",
        status=DocumentStatus.processing.value,
    )
    await db_session.commit()
    await db_session.refresh(document)
    return document


# ---------------------------------------------------------------------------
# _make_chunking_service unit tests
# ---------------------------------------------------------------------------


def test_make_chunking_service_returns_module_default_when_no_config() -> None:
    svc = _make_chunking_service(None)
    assert svc is document_tasks._chunking_service


def test_make_chunking_service_returns_module_default_for_empty_dict() -> None:
    svc = _make_chunking_service({})
    assert svc is document_tasks._chunking_service


def test_make_chunking_service_accepts_custom_strategy() -> None:
    svc = _make_chunking_service({"strategy": "paragraph_recursive"})
    assert svc._profile.strategy == "paragraph_recursive"
    assert svc is not document_tasks._chunking_service


def test_make_chunking_service_accepts_custom_chunk_sizes() -> None:
    svc = _make_chunking_service({"chunk_size_tokens": 400, "chunk_overlap_tokens": 50})
    assert svc.chunk_size_tokens == 400
    assert svc.chunk_overlap_tokens == 50


def test_make_chunking_service_falls_back_to_system_defaults_for_unset_sizes() -> None:
    svc = _make_chunking_service({"strategy": "token_recursive"})
    assert svc.chunk_size_tokens == settings.chunk_size_tokens
    assert svc.chunk_overlap_tokens == settings.chunk_overlap_tokens


def test_make_chunking_service_raises_for_invalid_overlap() -> None:
    with pytest.raises(ValueError, match="chunk_overlap_tokens"):
        _make_chunking_service({"chunk_size_tokens": 100, "chunk_overlap_tokens": 200})


# ---------------------------------------------------------------------------
# Task signature tests
# ---------------------------------------------------------------------------


def test_process_document_task_accepts_chunking_profile_config() -> None:
    import inspect

    sig = inspect.signature(document_tasks.process_document)
    assert "chunking_profile_config" in sig.parameters


def test_reindex_document_task_accepts_chunking_profile_config() -> None:
    import inspect

    sig = inspect.signature(document_tasks.reindex_document)
    assert "chunking_profile_config" in sig.parameters


def test_backfill_documents_task_is_registered() -> None:
    from app.workers.celery_app import celery_app

    assert "documents.backfill" in celery_app.tasks


# ---------------------------------------------------------------------------
# Integration: chunk_count and snapshot written after indexing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_count_persisted_on_document_after_indexing(
    db_session: AsyncSession,
    seeded_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"hello world content"))
    monkeypatch.setattr(document_tasks, "_embedding_service", FakeEmbeddingService())
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())

    _page_count, chunk_count, _, _ = await document_tasks._extract_and_store_document_pages_async(
        str(seeded_document.id)
    )

    repo = DocumentRepository()
    updated = await repo.get_document_by_id(db_session, document_id=seeded_document.id)
    assert updated is not None
    assert updated.chunk_count == chunk_count
    assert updated.chunk_count is not None and updated.chunk_count >= 1


@pytest.mark.asyncio
async def test_chunking_config_snapshot_contains_f212_fields(
    db_session: AsyncSession,
    seeded_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"sample text here"))
    monkeypatch.setattr(document_tasks, "_embedding_service", FakeEmbeddingService())
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())

    await document_tasks._extract_and_store_document_pages_async(
        str(seeded_document.id),
        profile_source="system_default",
    )

    repo = DocumentRepository()
    updated = await repo.get_document_by_id(db_session, document_id=seeded_document.id)
    assert updated is not None
    snapshot = updated.chunking_config_snapshot
    assert snapshot is not None
    assert snapshot["profile_source"] == "system_default"
    assert "ocr_applied" in snapshot
    assert "total_chunk_count" in snapshot
    assert "total_chunk_tokens" in snapshot
    assert snapshot["total_chunk_count"] >= 1


@pytest.mark.asyncio
async def test_custom_profile_snapshot_records_custom_source(
    db_session: AsyncSession,
    seeded_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"custom profile text"))
    monkeypatch.setattr(document_tasks, "_embedding_service", FakeEmbeddingService())
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())

    custom_svc = _make_chunking_service(
        {"strategy": "token_recursive", "chunk_size_tokens": 300, "chunk_overlap_tokens": 30}
    )
    await document_tasks._extract_and_store_document_pages_async(
        str(seeded_document.id),
        chunking_service=custom_svc,
        profile_source="custom_profile",
    )

    repo = DocumentRepository()
    updated = await repo.get_document_by_id(db_session, document_id=seeded_document.id)
    assert updated is not None
    assert updated.chunking_config_snapshot is not None
    assert updated.chunking_config_snapshot["profile_source"] == "custom_profile"
    assert updated.chunking_config_snapshot["chunk_size_tokens"] == 300


# ---------------------------------------------------------------------------
# Integration: chunking lifecycle events emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunking_started_and_completed_events_are_logged(
    db_session: AsyncSession,
    seeded_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"event test text"))
    monkeypatch.setattr(document_tasks, "_embedding_service", FakeEmbeddingService())
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())

    logged_events: list[str] = []

    original_log = document_tasks.log_document_event

    def capturing_log(*, event: str, **kwargs: Any) -> None:
        logged_events.append(event)
        original_log(event=event, **kwargs)

    monkeypatch.setattr(document_tasks, "log_document_event", capturing_log)

    await document_tasks._extract_and_store_document_pages_async(str(seeded_document.id))

    assert "document.chunking.started" in logged_events
    assert "document.chunking.completed" in logged_events


# ---------------------------------------------------------------------------
# Backfill task unit tests (no DB required)
# ---------------------------------------------------------------------------


def test_backfill_documents_raises_for_invalid_organization_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(document_tasks, "_run", lambda coro: None)
    with pytest.raises(PermanentTaskError, match="Invalid organization_id"):
        document_tasks.backfill_documents(
            organization_id="not-a-uuid",
        )


def test_backfill_documents_raises_for_invalid_chunking_profile_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # overlap >= size should be rejected before any DB call
    with pytest.raises(PermanentTaskError, match="Invalid chunking_profile_config"):
        document_tasks.backfill_documents(
            organization_id=str(uuid4()),
            chunking_profile_config={"chunk_size_tokens": 100, "chunk_overlap_tokens": 200},
        )


@pytest.mark.asyncio
async def test_backfill_dispatch_async_dispatches_one_task_per_indexed_document(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = Organization(name="Backfill Org", slug=f"backfill-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"bf-user-{uuid4().hex[:8]}",
        email=f"bf-{uuid4().hex[:8]}@example.com",
        display_name="BF User",
    )
    db_session.add(user)
    await db_session.flush()

    repo = DocumentRepository()
    for i in range(3):
        await repo.create_document(
            db_session,
            organization_id=org.id,
            uploaded_by_user_id=user.id,
            filename=f"doc{i}.txt",
            file_type="txt",
            storage_bucket="documents",
            storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
            status=DocumentStatus.indexed.value,
        )
    # One document NOT indexed — should be skipped.
    await repo.create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="pending.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
        status=DocumentStatus.uploaded.value,
    )
    await db_session.commit()

    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)

    dispatched_tasks: list[dict[str, Any]] = []
    monkeypatch.setattr(
        document_tasks.celery_app,
        "send_task",
        lambda name, *, kwargs: dispatched_tasks.append({"name": name, "kwargs": kwargs}),
    )

    count = await document_tasks._backfill_dispatch_async(
        org.id,
        chunking_profile_config=None,
        request_id=None,
        user_id=None,
    )

    assert count == 3
    assert len(dispatched_tasks) == 3
    assert all(t["name"] == "documents.reindex" for t in dispatched_tasks)
    dispatched_ids = {t["kwargs"]["document_id"] for t in dispatched_tasks}
    assert len(dispatched_ids) == 3
