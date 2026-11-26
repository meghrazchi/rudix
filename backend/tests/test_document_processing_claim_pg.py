"""PostgreSQL-backed concurrency and idempotency tests for the document processing claim."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

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
os.environ.setdefault("AUTH_PROVIDER", "clerk")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.com/.well-known/jwks.json")
os.environ.setdefault("CLERK_JWT_ISSUER", "https://clerk.example.com")
os.environ.setdefault("CLERK_JWT_AUDIENCE", "rudix-api")

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.db.session as db_session_module
import app.models  # noqa: F401  # register all mappers for relationship resolution
from app.clients import minio_client as minio_module
from app.core.config import settings
from app.domains.documents.repositories.processing_claims import (
    PROCESS_SKIP_STATUSES,
    ClaimOutcome,
    ClaimResult,
    DocumentProcessingClaimRepository,
)
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.models.organization import Organization
from app.models.user import User
from app.workers import document_tasks, notification_helper, status_tracking
from app.workers.async_runtime import run_async
from app.workers.celery_app import celery_app

pytestmark = pytest.mark.requires_postgres

_repo = DocumentProcessingClaimRepository()


async def _seed(
    factory: async_sessionmaker[AsyncSession],
    *,
    count: int = 1,
    status: str = DocumentStatus.uploaded.value,
    started_at: list[datetime | None] | None = None,
) -> tuple[UUID, list[UUID]]:
    suffix = uuid4().hex
    async with factory() as session:
        org = Organization(name=f"PG claim {suffix}", slug=f"pg-claim-{suffix}")
        session.add(org)
        await session.flush()
        user = User(
            organization_id=org.id,
            external_auth_id=f"pg-claim-{suffix}",
            email=f"pg-claim-{suffix}@example.com",
            display_name="PG Claim",
        )
        session.add(user)
        await session.flush()
        ids: list[UUID] = []
        for index in range(count):
            document = Document(
                organization_id=org.id,
                uploaded_by_user_id=user.id,
                filename="claim.txt",
                file_type="txt",
                storage_bucket="documents",
                storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
                status=status,
                processing_started_at=started_at[index] if started_at else None,
            )
            session.add(document)
            await session.flush()
            ids.append(document.id)
        await session.commit()
        return org.id, ids


async def _cleanup(factory: async_sessionmaker[AsyncSession], org_id: UUID) -> None:
    async with factory() as session:
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


async def _claim_in_own_session(
    factory: async_sessionmaker[AsyncSession], document_id: UUID, task_id: str
) -> tuple[str, ClaimResult]:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        result = await _repo.claim_for_processing(
            session,
            document_id=document_id,
            task_id=task_id,
            now=now,
            stale_before=now - timedelta(seconds=settings.document_processing_stale_seconds),
            force=False,
            skip_statuses=PROCESS_SKIP_STATUSES,
        )
    return task_id, result


async def _holder(factory: async_sessionmaker[AsyncSession], document_id: UUID) -> str | None:
    async with factory() as session:
        return (
            await session.execute(
                select(Document.processing_task_id).where(Document.id == document_id)
            )
        ).scalar_one()


@pytest.mark.parametrize("claimants", [2, 20])
async def test_concurrent_claims_have_exactly_one_winner(
    pg_session_factory: async_sessionmaker[AsyncSession], claimants: int
) -> None:
    org_id, (document_id,) = await _seed(pg_session_factory)
    try:
        results = await asyncio.gather(
            *(
                _claim_in_own_session(pg_session_factory, document_id, f"task-{index}")
                for index in range(claimants)
            )
        )
        winners = [task for task, result in results if result.outcome == ClaimOutcome.claimed]
        held = [result for _, result in results if result.outcome == ClaimOutcome.held]
        assert len(winners) == 1
        assert len(held) == claimants - 1
        assert all(result.current_status == DocumentStatus.processing.value for result in held)
        assert await _holder(pg_session_factory, document_id) == winners[0]
    finally:
        await _cleanup(pg_session_factory, org_id)


async def test_select_stale_processing_skips_locked_rows(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Ancient timestamps sort these rows ahead of any other stale rows in the shared DB.
    base = datetime(1990, 1, 1, tzinfo=UTC)
    started = [base + timedelta(seconds=index) for index in range(5)]
    org_id, ids = await _seed(
        pg_session_factory,
        count=5,
        status=DocumentStatus.processing.value,
        started_at=list(started),
    )
    stale_before = datetime.now(UTC)
    session_a = pg_session_factory()
    session_b = pg_session_factory()
    try:
        await session_a.begin()
        rows_a = await _repo.select_stale_processing(session_a, stale_before=stale_before, limit=3)
        await session_b.begin()
        rows_b = await _repo.select_stale_processing(session_b, stale_before=stale_before, limit=10)
        ids_a = {row.id for row in rows_a}
        ids_b = {row.id for row in rows_b}
        assert ids_a == set(ids[:3])
        assert ids_a.isdisjoint(ids_b)
        assert ids_b & set(ids) == set(ids[3:])
    finally:
        await session_a.rollback()
        await session_b.rollback()
        await session_a.close()
        await session_b.close()
        await _cleanup(pg_session_factory, org_id)


# ── Task-level idempotency (sync: run_async cannot nest inside an async test) ─────────


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        return None


class _FakeMinio:
    def get_object(self, **_: Any) -> dict[str, Any]:
        return {"Body": _Body(b"alpha line one\nbeta line two\ngamma line three")}


class _FlakyEmbeddingService:
    """Raises a transient error on the first call, then returns deterministic vectors."""

    def __init__(self) -> None:
        self.calls = 0

    async def embed_chunks(self, *, chunks: list[Any]) -> Any:
        self.calls += 1
        if self.calls == 1:
            raise document_tasks.DocumentPipelineTransientError(
                stage="embed",
                code="EMBEDDING_FAILED_TRANSIENT",
                category="infrastructure",
                message="embedding timeout",
            )
        tokens = sum(int(getattr(chunk, "token_count", 0)) for chunk in chunks)
        return type(
            "FakeEmbeddingResult",
            (),
            {
                "model_name": settings.openai_embedding_model,
                "index_version": settings.document_index_version,
                "batch_count": 1,
                "retry_count": 0,
                "input_tokens": tokens,
                "total_tokens": tokens,
                "latency_ms": 5,
                "approximate_cost_usd": Decimal("0.000001"),
                "vectors_by_chunk_id": {
                    chunk.id: [0.001] * settings.qdrant_vector_size for chunk in chunks
                },
            },
        )()


class _FakeQdrant:
    def __init__(self) -> None:
        self.upserts: list[list[str]] = []

    @staticmethod
    def build_point_id(*, document_id: UUID, chunk_index: int, index_version: str) -> str:
        return f"{document_id}:{index_version}:{chunk_index}"

    async def upsert_chunks(self, *, chunks: list[Any], **_: Any) -> Any:
        self.upserts.append([str(chunk.qdrant_point_id) for chunk in chunks])
        return type("Upsert", (), {"upserted_count": len(chunks), "batch_count": 1})()

    async def delete_document_points(self, **_: Any) -> Any:
        return type("Delete", (), {"deleted": True})()


@pytest.fixture
def worker_pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL-backed tests")
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    for module in (document_tasks, status_tracking, db_session_module):
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(notification_helper, "emit_notification", lambda **_: None)
    always_eager = celery_app.conf.task_always_eager
    eager_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    try:
        yield factory
    finally:
        celery_app.conf.task_always_eager = always_eager
        celery_app.conf.task_eager_propagates = eager_propagates
        run_async(engine.dispose())


async def _document_state(
    factory: async_sessionmaker[AsyncSession], document_id: UUID
) -> tuple[Document, list[DocumentChunk]]:
    async with factory() as session:
        document = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one()
        chunks = list(
            (
                await session.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == document_id,
                        DocumentChunk.index_version == settings.document_index_version,
                    )
                )
            )
            .scalars()
            .all()
        )
        return document, chunks


async def _preset_claim(
    factory: async_sessionmaker[AsyncSession], document_id: UUID, task_id: str
) -> None:
    async with factory() as session:
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                status=DocumentStatus.processing.value,
                processing_task_id=task_id,
                processing_started_at=datetime.now(UTC),
            )
        )
        await session.commit()


def test_process_task_retry_and_redelivery_are_idempotent(
    worker_pg: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = worker_pg
    embeddings = _FlakyEmbeddingService()
    qdrant = _FakeQdrant()
    monkeypatch.setattr(minio_module, "minio_client", _FakeMinio())
    monkeypatch.setattr(document_tasks, "_embedding_service", embeddings)
    monkeypatch.setattr(document_tasks, "_qdrant_service", qdrant)

    org_id, (document_id,) = run_async(_seed(factory))
    try:
        # 1) Transient failure on the first attempt, autoretry with the same task id.
        result = document_tasks.process_document.apply(
            args=[str(document_id)], kwargs={}, task_id="fixed-task-id"
        )
        assert result.successful(), result.result
        assert result.result["status"] == DocumentStatus.indexed.value
        assert embeddings.calls == 2

        document, chunks = run_async(_document_state(factory, document_id))
        assert document.status == DocumentStatus.indexed.value
        assert document.processing_task_id is None
        assert document.processing_started_at is None
        assert document.processing_reap_count == 0
        assert len(chunks) == result.result["chunk_count"]
        assert len(qdrant.upserts) == 1
        point_ids = qdrant.upserts[0]
        assert len(point_ids) == len(set(point_ids))
        assert set(point_ids) == {chunk.qdrant_point_id for chunk in chunks}

        # 2) A different task while t1 holds a fresh claim skips.
        run_async(_preset_claim(factory, document_id, "t1"))
        skipped = document_tasks.process_document.apply(args=[str(document_id)], task_id="t2")
        assert skipped.result == {"document_id": str(document_id), "status": "skipped"}

        # 3) Redelivery of t1 re-enters its claim and completes without duplicates.
        redelivered = document_tasks.process_document.apply(args=[str(document_id)], task_id="t1")
        assert redelivered.successful(), redelivered.result
        assert redelivered.result["status"] == DocumentStatus.indexed.value
        document, rerun_chunks = run_async(_document_state(factory, document_id))
        assert document.status == DocumentStatus.indexed.value
        assert document.processing_task_id is None
        assert len(rerun_chunks) == len(chunks)
        assert {chunk.qdrant_point_id for chunk in rerun_chunks} == set(point_ids)
        assert len(qdrant.upserts) == 2
        assert qdrant.upserts[1] == point_ids
    finally:
        run_async(_cleanup(factory, org_id))
