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
from app.models.pipeline import PipelineEvent, PipelineRun
from app.models.usage import AuditLog, UsageEvent
from app.models.user import User
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
        self.delete_calls: list[dict[str, Any]] = []

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
        chunking_strategy: str | None = None,
        chunking_profile_version: str | None = None,
        parent_text_by_chunk_id: dict[UUID, str] | None = None,
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

    async def delete_document_points(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        index_version: str | None = None,
    ) -> Any:
        self.delete_calls.append(
            {
                "organization_id": organization_id,
                "document_id": document_id,
                "index_version": index_version,
            }
        )
        return type("FakeQdrantDeleteResult", (), {"deleted": True})()


class FakeQdrantDeleteService(FakeQdrantService):
    def __init__(self) -> None:
        super().__init__()
        self.delete_calls: list[dict[str, Any]] = []

    async def delete_document_points(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        index_version: str | None = None,
    ) -> Any:
        self.delete_calls.append(
            {
                "organization_id": organization_id,
                "document_id": document_id,
                "index_version": index_version,
            }
        )
        return type("FakeQdrantDeleteResult", (), {"deleted": True})()


class FailingQdrantService(FakeQdrantService):
    async def upsert_chunks(self, **_: Any) -> Any:
        raise RuntimeError("qdrant is unavailable")


class EmptyChunkingService:
    async def chunk(self, **_: Any) -> list[Any]:
        return []


class FakeMinioDeleter:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys
        self.list_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.list_calls.append(kwargs)
        prefix = str(kwargs.get("Prefix", ""))
        contents = [{"Key": key} for key in self._keys if key.startswith(prefix)]
        return {
            "IsTruncated": False,
            "Contents": contents,
        }

    def delete_object(self, **kwargs: Any) -> None:
        self.delete_calls.append(kwargs)


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
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    fake_minio = FakeMinioReader(b"line one\nline two")
    fake_qdrant = FakeQdrantService()
    monkeypatch.setattr(minio_module, "minio_client", fake_minio)
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        FakeEmbeddingService(dimension=settings.qdrant_vector_size),
    )
    monkeypatch.setattr(document_tasks, "_qdrant_service", fake_qdrant)
    document_id = seeded_txt_document.id

    (
        page_count,
        chunk_count,
        cleaning_stats,
        embedding_result,
    ) = await document_tasks._extract_and_store_document_pages_async(str(document_id))
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
    assert len(fake_qdrant.delete_calls) == 1
    assert fake_qdrant.delete_calls[0]["document_id"] == document_id
    assert fake_qdrant.delete_calls[0]["organization_id"] == seeded_txt_document.organization_id
    assert fake_qdrant.delete_calls[0]["index_version"] == settings.document_index_version
    qdrant_call = fake_qdrant.calls[0]
    assert qdrant_call["document_id"] == document_id
    assert qdrant_call["filename"] == seeded_txt_document.filename
    assert qdrant_call["file_type"] == seeded_txt_document.file_type
    assert len(qdrant_call["vectors_by_chunk_id"]) == len(chunks)
    usage_events = list((await db_session.execute(select(UsageEvent))).scalars().all())
    assert len(usage_events) == 1
    assert usage_events[0].event_type == "document.embedding"
    assert usage_events[0].model_name == settings.openai_embedding_model
    pipeline_runs = list((await db_session.execute(select(PipelineRun))).scalars().all())
    assert len(pipeline_runs) == 1
    pipeline_run = pipeline_runs[0]
    assert pipeline_run.pipeline_type == "document.process"
    assert pipeline_run.status == "completed"
    assert pipeline_run.document_id == document_id
    assert pipeline_run.organization_id == seeded_txt_document.organization_id
    pipeline_events = list(
        (
            await db_session.execute(
                select(PipelineEvent)
                .where(PipelineEvent.pipeline_run_id == pipeline_run.id)
                .order_by(PipelineEvent.sequence.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(pipeline_events) >= 8
    assert pipeline_events[0].node_name == "extract"
    assert pipeline_events[0].status == "started"
    assert any(
        event.node_name == "index" and event.status == "completed" for event in pipeline_events
    )

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
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b" \n\t "))
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        FakeEmbeddingService(dimension=settings.qdrant_vector_size),
    )
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())

    with pytest.raises(PermanentTaskError, match="extracted document contains no text"):
        await document_tasks._extract_and_store_document_pages_async(str(seeded_txt_document.id))


@pytest.mark.asyncio
async def test_worker_replaces_chunks_idempotently_for_same_index_version(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(
        minio_module, "minio_client", FakeMinioReader(b"line one\nline two\nline three")
    )
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        FakeEmbeddingService(dimension=settings.qdrant_vector_size),
    )
    fake_qdrant = FakeQdrantService()
    monkeypatch.setattr(document_tasks, "_qdrant_service", fake_qdrant)

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
    assert len(fake_qdrant.delete_calls) == 2
    assert all(
        call["index_version"] == settings.document_index_version
        for call in fake_qdrant.delete_calls
    )


@pytest.mark.asyncio
async def test_worker_fails_when_embedding_dimension_is_invalid(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
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
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"line one\nline two"))
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        FakeEmbeddingService(dimension=settings.qdrant_vector_size),
    )
    monkeypatch.setattr(document_tasks, "_qdrant_service", FailingQdrantService())

    with pytest.raises(TransientTaskError, match="qdrant upsert failed"):
        await document_tasks._extract_and_store_document_pages_async(str(seeded_txt_document.id))


@pytest.mark.asyncio
async def test_worker_fails_when_chunking_produces_no_chunks(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(minio_module, "minio_client", FakeMinioReader(b"line one\nline two"))
    monkeypatch.setattr(document_tasks, "_chunking_service", EmptyChunkingService())
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        FakeEmbeddingService(dimension=settings.qdrant_vector_size),
    )
    monkeypatch.setattr(document_tasks, "_qdrant_service", FakeQdrantService())

    with pytest.raises(PermanentTaskError, match="cleaned document produced no chunks"):
        await document_tasks._extract_and_store_document_pages_async(str(seeded_txt_document.id))


@pytest.mark.asyncio
async def test_delete_worker_removes_vectors_storage_and_local_metadata(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = seeded_txt_document.id
    organization_id = seeded_txt_document.organization_id
    uploaded_by_user_id = seeded_txt_document.uploaded_by_user_id
    storage_bucket = seeded_txt_document.storage_bucket
    storage_object_key = seeded_txt_document.storage_object_key

    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)

    repository = DocumentRepository()
    _ = await repository.update_document_status(
        db_session,
        document_id=document_id,
        status=DocumentStatus.indexed.value,
        page_count=1,
    )
    await repository.create_document_page(
        db_session,
        document_id=document_id,
        page_number=1,
        text="hello world",
        char_count=11,
    )
    await repository.create_document_chunk(
        db_session,
        document_id=document_id,
        page_number=1,
        chunk_index=0,
        text="hello world",
        token_count=2,
        embedding_model=settings.openai_embedding_model,
        index_version=settings.document_index_version,
        qdrant_point_id=f"{document_id}:{settings.document_index_version}:0",
    )
    await db_session.commit()

    object_prefix = storage_object_key.rsplit(".", maxsplit=1)[0]
    fake_minio = FakeMinioDeleter(
        keys=[
            storage_object_key,
            f"{object_prefix}.meta.json",
        ]
    )
    fake_qdrant = FakeQdrantDeleteService()
    fake_graph_calls: list[dict[str, Any]] = []

    class FakeGraphService:
        async def clear_document_graph_facts(self, **kwargs: Any) -> dict[str, int]:
            fake_graph_calls.append(kwargs)
            return {
                "evidence_deleted": 1,
                "relations_deleted": 1,
                "aliases_deleted": 1,
                "chunks_deleted": 1,
                "orphan_entities_deleted": 1,
                "document_node_deleted": True,
            }

    monkeypatch.setattr(minio_module, "minio_client", fake_minio)
    monkeypatch.setattr(document_tasks, "_qdrant_service", fake_qdrant)
    monkeypatch.setattr(document_tasks, "_graph_service", FakeGraphService())

    deleted_chunks, deleted_pages = await document_tasks._delete_document_assets_async(
        str(document_id),
        request_id="req-delete-worker-1",
        organization_id=str(organization_id),
        user_id=str(uploaded_by_user_id),
    )
    assert deleted_chunks == 1
    assert deleted_pages == 1
    assert len(fake_qdrant.delete_calls) == 1
    assert fake_qdrant.delete_calls[0]["organization_id"] == organization_id
    assert fake_qdrant.delete_calls[0]["document_id"] == document_id
    assert len(fake_graph_calls) == 1
    assert fake_graph_calls[0]["delete_document_node"] is True
    assert len(fake_minio.list_calls) == 1
    assert fake_minio.list_calls[0]["Bucket"] == storage_bucket
    assert fake_minio.list_calls[0]["Prefix"] == object_prefix
    deleted_keys = [call["Key"] for call in fake_minio.delete_calls]
    assert storage_object_key in deleted_keys
    assert f"{object_prefix}.meta.json" in deleted_keys

    db_session.expire_all()
    document = await repository.get_document_by_id(db_session, document_id=document_id)
    assert document is not None
    assert document.status == DocumentStatus.deleted.value
    pages = await repository.list_document_pages(db_session, document_id=document_id)
    chunks = await repository.list_document_chunks(
        db_session,
        document_id=document_id,
        index_version=None,
    )
    assert pages == []
    assert chunks == []


@pytest.mark.asyncio
async def test_delete_worker_is_idempotent_when_document_is_already_deleted(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.deleted.value,
    )
    monkeypatch.setattr(
        document_tasks,
        "_run",
        lambda *_: (_ for _ in ()).throw(AssertionError("delete flow should be skipped")),
    )

    result = document_tasks.delete_document.run(str(seeded_txt_document.id))
    assert result["document_id"] == str(seeded_txt_document.id)
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_document_worker_audit_helper_writes_log(
    db_session: AsyncSession,
    seeded_txt_document: Document,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(document_tasks, "SessionLocal", session_factory)

    await document_tasks._record_worker_audit_async(
        action="document.delete.completed",
        resource_type="document",
        resource_id=str(seeded_txt_document.id),
        organization_id=str(seeded_txt_document.organization_id),
        user_id=None,
        request_id="req-delete-task-audit",
        metadata={
            "deleted_chunk_count": 2,
            "deleted_page_count": 1,
            "status": DocumentStatus.deleted.value,
        },
    )
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "document.delete.completed"
    assert audit_logs[0].resource_id == seeded_txt_document.id
    assert audit_logs[0].metadata_json["deleted_chunk_count"] == 2
    assert audit_logs[0].metadata_json["deleted_page_count"] == 1
    assert audit_logs[0].metadata_json["request_id"] == "req-delete-task-audit"
