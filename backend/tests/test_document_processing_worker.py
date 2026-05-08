from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app")
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
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import UsageEvent
from app.models.user import User
from app.repositories.documents import DocumentRepository
from app.workers import document_tasks
from app.workers.base_task import PermanentTaskError, TransientTaskError


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.closed = False

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        self.closed = True


class FakeMinioReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls: list[dict[str, Any]] = []

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"Body": _Body(self.data)}


class FakeEmbeddingService:
    def __init__(self, *, dimension: int = 1536) -> None:
        self.dimension = dimension
        self.calls: list[list[Any]] = []

    async def embed_chunks(self, *, chunks: list[Any]) -> Any:
        self.calls.append(chunks)
        input_tokens = sum(int(getattr(chunk, "token_count", 0)) for chunk in chunks)
        return type(
            "FakeEmbeddingResult",
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
                "vectors_by_chunk_id": {chunk.id: [0.001] * self.dimension for chunk in chunks},
            },
        )()


class FakeQdrantService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def build_point_id(*, document_id: UUID, chunk_index: int, index_version: str) -> str:
        return f"{document_id}:{index_version}:{chunk_index}"

    async def upsert_chunks(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        document_id: UUID,
        filename: str,
        file_type: str,
        chunks: list[Any],
        vectors_by_chunk_id: dict[UUID, list[float]],
    ) -> Any:
        call_payload = {
            "organization_id": organization_id,
            "user_id": user_id,
            "document_id": document_id,
            "filename": filename,
            "file_type": file_type,
            "chunks": chunks,
            "vectors_by_chunk_id": vectors_by_chunk_id,
        }
        self.calls.append(call_payload)

        return type(
            "FakeQdrantUpsertResult",
            (),
            {
                "upserted_count": len(chunks),
                "batch_count": 1,
            },
        )()


class FailingQdrantService(FakeQdrantService):
    async def upsert_chunks(self, **_: Any) -> Any:
        raise RuntimeError("qdrant is unavailable")


@pytest_asyncio.fixture
async def seeded_txt_document(db_session: AsyncSession) -> Document:
    org = Organization(name="Extraction Org", slug=f"extract-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"extract-user-{uuid4().hex[:8]}",
        email=f"extract-{uuid4().hex[:8]}@example.com",
        display_name="Extraction User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrganizationRole.member.value))
    await db_session.flush()

    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="worker.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{user.id}/{uuid4()}.txt",
        status=DocumentStatus.processing.value,
    )
    await db_session.commit()
    await db_session.refresh(document)
    return document


@pytest.mark.asyncio
async def test_worker_extracts_text_and_persists_document_pages(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    fake_minio = FakeMinioReader(b"line one\nline two")
    fake_qdrant = FakeQdrantService()
    monkeypatch.setattr(minio_module, "minio_client", fake_minio)
    monkeypatch.setattr(document_tasks, "_embedding_service", FakeEmbeddingService(dimension=settings.qdrant_vector_size))
    monkeypatch.setattr(document_tasks, "_qdrant_service", fake_qdrant)
    document_id = seeded_txt_document.id

    page_count, chunk_count, cleaning_stats, embedding_result = await document_tasks._extract_and_store_document_pages_async(
        str(document_id)
    )
    assert page_count == 1
    assert chunk_count >= 1
    assert embedding_result.batch_count == 1
    assert cleaning_stats.pages_total == 1
    assert cleaning_stats.chars_after == len("line one\nline two")
    assert len(fake_minio.calls) == 1
    assert fake_minio.calls[0]["Bucket"] == seeded_txt_document.storage_bucket
    assert fake_minio.calls[0]["Key"] == seeded_txt_document.storage_object_key

    repository = DocumentRepository()
    pages = await repository.list_document_pages(db_session, document_id=document_id)
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert pages[0].text == "line one\nline two"
    assert pages[0].char_count == len("line one\nline two")
    chunks = await repository.list_document_chunks(
        db_session,
        document_id=document_id,
        index_version=settings.document_index_version,
    )
    assert len(chunks) == chunk_count
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.token_count > 0 for chunk in chunks)
    assert all(chunk.embedding_model == settings.openai_embedding_model for chunk in chunks)
    assert all(chunk.index_version == settings.document_index_version for chunk in chunks)
    assert all(chunk.qdrant_point_id is not None for chunk in chunks)
    assert [chunk.qdrant_point_id for chunk in chunks] == [
        f"{document_id}:{settings.document_index_version}:{index}" for index in range(len(chunks))
    ]
    assert len(fake_qdrant.calls) == 1
    qdrant_call = fake_qdrant.calls[0]
    assert qdrant_call["document_id"] == document_id
    assert qdrant_call["filename"] == seeded_txt_document.filename
    assert qdrant_call["file_type"] == seeded_txt_document.file_type
    assert len(qdrant_call["vectors_by_chunk_id"]) == len(chunks)
    usage_events = list((await db_session.execute(select(UsageEvent))).scalars().all())
    assert len(usage_events) == 1
    assert usage_events[0].event_type == "document.embedding"
    assert usage_events[0].model_name == settings.openai_embedding_model

    db_session.expire_all()
    result = await db_session.execute(select(Document).where(Document.id == UUID(str(document_id))))
    updated = result.scalar_one()
    assert updated.status == DocumentStatus.indexed.value
    assert updated.page_count == 1


@pytest.mark.asyncio
async def test_worker_fails_on_empty_extraction(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b" \n\t "))
    monkeypatch.setattr(document_tasks, "_embedding_service", FakeEmbeddingService(dimension=settings.qdrant_vector_size))
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())

    with pytest.raises(PermanentTaskError, match="extracted document contains no text"):
        await document_tasks._extract_and_store_document_pages_async(str(seeded_txt_document.id))


@pytest.mark.asyncio
async def test_worker_replaces_chunks_idempotently_for_same_index_version(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"line one\nline two\nline three"))
    monkeypatch.setattr(document_tasks, "_embedding_service", FakeEmbeddingService(dimension=settings.qdrant_vector_size))
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())

    document_id = seeded_txt_document.id
    repository = DocumentRepository()

    await document_tasks._extract_and_store_document_pages_async(str(document_id))
    first_chunks = await repository.list_document_chunks(
        db_session,
        document_id=document_id,
        index_version=settings.document_index_version,
    )
    first_snapshot = [
        (
            chunk.chunk_index,
            chunk.page_number,
            chunk.text,
            chunk.token_count,
            chunk.qdrant_point_id,
            chunk.embedding_model,
            chunk.index_version,
        )
        for chunk in first_chunks
    ]

    await document_tasks._extract_and_store_document_pages_async(str(document_id))
    second_chunks = await repository.list_document_chunks(
        db_session,
        document_id=document_id,
        index_version=settings.document_index_version,
    )
    second_snapshot = [
        (
            chunk.chunk_index,
            chunk.page_number,
            chunk.text,
            chunk.token_count,
            chunk.qdrant_point_id,
            chunk.embedding_model,
            chunk.index_version,
        )
        for chunk in second_chunks
    ]

    assert first_snapshot
    assert second_snapshot == first_snapshot


@pytest.mark.asyncio
async def test_worker_fails_when_embedding_dimension_is_invalid(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"line one\nline two"))
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        FakeEmbeddingService(dimension=settings.qdrant_vector_size + 1),
    )

    with pytest.raises(PermanentTaskError, match="embedding dimension mismatch"):
        await document_tasks._extract_and_store_document_pages_async(str(seeded_txt_document.id))


@pytest.mark.asyncio
async def test_worker_fails_when_qdrant_upsert_fails(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"line one\nline two"))
    monkeypatch.setattr(document_tasks, "_embedding_service", FakeEmbeddingService(dimension=settings.qdrant_vector_size))
    monkeypatch.setattr(document_tasks, "_qdrant_service", FailingQdrantService())

    with pytest.raises(TransientTaskError, match="qdrant upsert failed"):
        await document_tasks._extract_and_store_document_pages_async(str(seeded_txt_document.id))
