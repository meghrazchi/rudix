"""R02-05: evaluation re-ingest removes its eval- chunks and vectors."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
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

from app.core.config import settings
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.models.document import DocumentChunk
from app.models.enums import DocumentStatus, EvaluationRunStatus
from app.models.evaluation import EvaluationRun
from app.models.organization import Organization
from app.models.user import User
from app.workers import document_tasks, evaluation_index_cleanup, evaluation_tasks
from app.workers.evaluation_index_cleanup import (
    EvalIndexCleanupResult,
    cleanup_eval_index_version_async,
)

EVAL_VERSION = "eval-0123456789-2"


class _FakeQdrantService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def delete_document_points(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("qdrant down: secret-token")


async def _seed_document(db_session: AsyncSession) -> tuple[Organization, Any]:
    org = Organization(name="Cleanup Org", slug=f"cleanup-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"cleanup-{uuid4().hex[:8]}",
        email=f"cleanup-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    repo = DocumentRepository()
    document = await repo.create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="policy.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{uuid4().hex}.pdf",
        status=DocumentStatus.indexed.value,
    )
    for version in (settings.document_index_version, EVAL_VERSION):
        for index in range(2):
            await repo.create_document_chunk(
                db_session,
                document_id=document.id,
                page_number=1,
                chunk_index=index,
                text="Employees receive twenty days of annual leave.",
                token_count=10,
                embedding_model=settings.openai_embedding_model,
                index_version=version,
                qdrant_point_id=f"{document.id}:{version}:{index}",
            )
    await db_session.commit()
    return org, document


async def _versions(db_session: AsyncSession, document_id: UUID) -> list[str]:
    rows = await db_session.execute(
        select(DocumentChunk.index_version).where(DocumentChunk.document_id == document_id)
    )
    return sorted(rows.scalars())


def _bind_sessions(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(evaluation_index_cleanup, "SessionLocal", factory)
    monkeypatch.setattr(evaluation_tasks, "SessionLocal", factory)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_deletes_only_eval_version(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, document = await _seed_document(db_session)
    _bind_sessions(monkeypatch, db_session)
    fake_qdrant = _FakeQdrantService()
    monkeypatch.setattr(document_tasks, "_qdrant_service", fake_qdrant)

    result = await cleanup_eval_index_version_async(
        organization_id=org.id, document_ids=[document.id], index_version=EVAL_VERSION
    )

    assert result == EvalIndexCleanupResult(
        index_version=EVAL_VERSION,
        documents_attempted=1,
        chunks_deleted=2,
        qdrant_failures=0,
        chunk_failures=0,
    )
    assert result.as_dict()["chunks_deleted"] == 2
    assert fake_qdrant.calls == [
        {"organization_id": org.id, "document_id": document.id, "index_version": EVAL_VERSION}
    ]
    assert await _versions(db_session, document.id) == [settings.document_index_version] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["v1", "v0", "legacy"])
async def test_cleanup_refuses_non_eval_versions(version: str) -> None:
    with pytest.raises(ValueError, match="only eval-"):
        await cleanup_eval_index_version_async(
            organization_id=uuid4(), document_ids=[uuid4()], index_version=version
        )


@pytest.mark.asyncio
async def test_cleanup_refuses_active_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    # The validator forbids this configuration; the helper must still refuse it.
    monkeypatch.setattr(settings, "document_active_index_versions", [EVAL_VERSION])
    with pytest.raises(ValueError, match="active index version"):
        await cleanup_eval_index_version_async(
            organization_id=uuid4(), document_ids=[uuid4()], index_version=EVAL_VERSION
        )


@pytest.mark.asyncio
async def test_cleanup_counts_qdrant_failure_and_still_deletes_chunks(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, document = await _seed_document(db_session)
    _bind_sessions(monkeypatch, db_session)
    monkeypatch.setattr(document_tasks, "_qdrant_service", _FakeQdrantService(fail=True))
    failures: list[str] = []
    monkeypatch.setattr(
        evaluation_index_cleanup,
        "record_eval_index_cleanup_failure",
        lambda *, store: failures.append(store),
    )

    result = await cleanup_eval_index_version_async(
        organization_id=org.id, document_ids=[document.id], index_version=EVAL_VERSION
    )

    assert result.qdrant_failures == 1
    assert result.chunks_deleted == 2
    assert failures == ["qdrant"]
    assert await _versions(db_session, document.id) == [settings.document_index_version] * 2


@pytest.mark.asyncio
async def test_cleanup_counts_chunk_failure(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, document = await _seed_document(db_session)
    _bind_sessions(monkeypatch, db_session)
    monkeypatch.setattr(document_tasks, "_qdrant_service", _FakeQdrantService())
    failures: list[str] = []
    monkeypatch.setattr(
        evaluation_index_cleanup,
        "record_eval_index_cleanup_failure",
        lambda *, store: failures.append(store),
    )

    async def _boom(self: DocumentRepository, session: AsyncSession, **kwargs: Any) -> int:
        raise RuntimeError("db down")

    monkeypatch.setattr(DocumentRepository, "delete_document_chunks", _boom)

    result = await cleanup_eval_index_version_async(
        organization_id=org.id, document_ids=[document.id], index_version=EVAL_VERSION
    )

    assert result.chunk_failures == 1
    assert result.chunks_deleted == 0
    assert failures == ["postgres"]


def test_record_eval_index_cleanup_failure_increments_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import metrics

    monkeypatch.setattr(metrics, "is_metrics_enabled", lambda: True)
    counter = metrics.EVAL_INDEX_CLEANUP_FAILURES_TOTAL.labels(store="qdrant")
    before = counter._value.get()
    metrics.record_eval_index_cleanup_failure(store="qdrant")
    assert counter._value.get() == before + 1

    monkeypatch.setattr(metrics, "is_metrics_enabled", lambda: False)
    metrics.record_eval_index_cleanup_failure(store="qdrant")
    assert counter._value.get() == before + 1


# ---------------------------------------------------------------------------
# Evaluation run wiring
# ---------------------------------------------------------------------------


class _FakeLLMService:
    def __init__(self, **kwargs: Any) -> None:
        self.model_name = settings.openai_llm_model

    async def generate_answer(self, **kwargs: Any) -> object:
        return type(
            "R",
            (),
            {
                "answer": "Employees receive twenty days of annual leave.",
                "not_found": False,
                "citations": [],
                "model_name": self.model_name,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "approximate_cost_usd": Decimal("0"),
                "latency_ms": 1,
                "retry_count": 0,
                "used_fallback_parser": False,
            },
        )()


class _FakeRetrieval:
    embedding_model = settings.openai_embedding_model

    async def embed_query(self, **kwargs: Any) -> tuple[list[float], int]:
        return [0.01] * settings.qdrant_vector_size, 1

    def retrieve_candidates(self, **kwargs: Any) -> list[Any]:
        return []


async def _seed_comparison_run(db_session: AsyncSession) -> tuple[str, UUID, UUID]:
    org, document = await _seed_document(db_session)
    repo = EvaluationRepository()
    evaluation_set = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Cleanup set"
    )
    await repo.create_evaluation_question(
        db_session,
        evaluation_set_id=evaluation_set.id,
        question="How much leave?",
        expected_answer="Twenty days.",
        expected_document_id=document.id,
        expected_page_number=1,
    )
    run = await repo.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.queued.value,
        config={
            "top_k": 3,
            "rerank": False,
            "model_name": settings.openai_llm_model,
            "selected_document_ids": [str(document.id)],
            "comparison_targets": [
                {
                    "label": label,
                    "chunking_profile_id": f"profile-{label}",
                    "chunking_profile_config": {"strategy": "token_recursive"},
                    "chunking_strategy": "token_recursive",
                    "profile_version": f"cfg-{label}",
                    "profile_source": "organization_profile",
                }
                for label in ("a", "b")
            ],
        },
    )
    await db_session.commit()
    return str(run.id), org.id, document.id


def _stats() -> evaluation_tasks.ChunkingCorpusStats:
    return evaluation_tasks.ChunkingCorpusStats(
        chunk_count_total=1,
        chunk_tokens_average=10.0,
        chunk_tokens_variance=0.0,
        chunk_tokens_min=10,
        chunk_tokens_max=10,
        document_type_breakdown={"pdf": 1},
        language_breakdown={"en": 1},
        ocr_breakdown={"native_text": 1},
    )


def _wire_run(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    *,
    fail_on_target: int | None = None,
) -> list[dict[str, Any]]:
    _bind_sessions(monkeypatch, db_session)
    monkeypatch.setattr(evaluation_tasks, "LLMService", _FakeLLMService)
    monkeypatch.setattr(evaluation_tasks, "_query_retrieval_service", _FakeRetrieval())

    async def fake_prepare(
        *, evaluation_run_id: UUID, target_index: int, **kwargs: Any
    ) -> tuple[str, evaluation_tasks.ChunkingCorpusStats]:
        if target_index == fail_on_target:
            raise RuntimeError("re-ingest failed midway")
        version = evaluation_tasks._build_target_index_version(
            evaluation_run_id=evaluation_run_id, target_index=target_index
        )
        return version, _stats()

    cleanup_calls: list[dict[str, Any]] = []

    async def fake_cleanup(
        *, organization_id: UUID, document_ids: list[UUID], index_version: str
    ) -> EvalIndexCleanupResult:
        cleanup_calls.append(
            {
                "organization_id": organization_id,
                "document_ids": list(document_ids),
                "index_version": index_version,
            }
        )
        return EvalIndexCleanupResult(
            index_version=index_version,
            documents_attempted=len(document_ids),
            chunks_deleted=2,
            qdrant_failures=0,
            chunk_failures=0,
        )

    monkeypatch.setattr(evaluation_tasks, "_prepare_chunking_target_corpus_async", fake_prepare)
    monkeypatch.setattr(evaluation_tasks, "cleanup_eval_index_version_async", fake_cleanup)
    return cleanup_calls


@pytest.mark.asyncio
async def test_comparison_run_cleans_up_each_profile_target(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, org_id, document_id = await _seed_comparison_run(db_session)
    cleanup_calls = _wire_run(monkeypatch, db_session)

    result = await evaluation_tasks._run_evaluation_async(run_id)

    run_hex = UUID(run_id).hex[:10]
    assert cleanup_calls == [
        {
            "organization_id": org_id,
            "document_ids": [document_id],
            "index_version": f"eval-{run_hex}-{n}",
        }
        for n in (1, 2)
    ]
    entries = result["metrics_summary"]["eval_index_cleanup"]
    assert [entry["index_version"] for entry in entries] == [
        f"eval-{run_hex}-1",
        f"eval-{run_hex}-2",
    ]
    assert all(entry["chunks_deleted"] == 2 for entry in entries)
    run_row = (
        await db_session.execute(select(EvaluationRun).where(EvaluationRun.id == UUID(run_id)))
    ).scalar_one()
    await db_session.refresh(run_row)
    assert len(run_row.config["metrics_summary"]["eval_index_cleanup"]) == 2


@pytest.mark.asyncio
async def test_cleanup_runs_when_prepare_fails_midway(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _, _ = await _seed_comparison_run(db_session)
    cleanup_calls = _wire_run(monkeypatch, db_session, fail_on_target=1)

    with pytest.raises(RuntimeError, match="re-ingest failed midway"):
        await evaluation_tasks._run_evaluation_async(run_id)

    run_hex = UUID(run_id).hex[:10]
    assert [call["index_version"] for call in cleanup_calls] == [
        f"eval-{run_hex}-1",
        f"eval-{run_hex}-2",
    ]


@pytest.mark.asyncio
async def test_live_index_target_is_not_cleaned_up(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _, _ = await _seed_comparison_run(db_session)
    run_row = (
        await db_session.execute(select(EvaluationRun).where(EvaluationRun.id == UUID(run_id)))
    ).scalar_one()
    run_row.config = {
        key: value for key, value in run_row.config.items() if key != "comparison_targets"
    }
    await db_session.commit()
    cleanup_calls = _wire_run(monkeypatch, db_session)

    async def live_prepare(**kwargs: Any) -> tuple[str, evaluation_tasks.ChunkingCorpusStats]:
        return settings.document_index_version, _stats()

    monkeypatch.setattr(evaluation_tasks, "_prepare_chunking_target_corpus_async", live_prepare)

    result = await evaluation_tasks._run_evaluation_async(run_id)

    assert cleanup_calls == []
    assert result["metrics_summary"]["eval_index_cleanup"] == []


# ---------------------------------------------------------------------------
# Evaluation re-ingest leaves production graph facts alone
# ---------------------------------------------------------------------------


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
        return {"Body": _Body(b"Employees receive twenty days of annual leave.")}


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


class _FakePipelineQdrant:
    @staticmethod
    def build_point_id(*, document_id: UUID, chunk_index: int, index_version: str) -> str:
        return f"{document_id}:{index_version}:{chunk_index}"

    async def upsert_chunks(self, *, chunks: list[Any], **_: Any) -> Any:
        return type("R", (), {"upserted_count": len(chunks), "batch_count": 1})()

    async def delete_document_points(self, **_: Any) -> Any:
        return type("R", (), {"deleted": True})()


@pytest.mark.asyncio
@pytest.mark.parametrize("persist_document_state", [False, True])
async def test_eval_reingest_skips_graph_extraction(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    persist_document_state: bool,
) -> None:
    from app.clients import minio_client as minio_module

    org = Organization(name="Graph Skip Org", slug=f"graph-skip-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"graph-skip-{uuid4().hex[:8]}",
        email=f"graph-skip-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    document = await DocumentRepository().create_document(
        db_session,
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="leave.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"seed/{uuid4().hex}.txt",
        status=DocumentStatus.indexed.value,
    )
    await db_session.commit()

    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(document_tasks, "SessionLocal", factory)
    monkeypatch.setattr(minio_module, "minio_client", _FakeMinio())
    monkeypatch.setattr(document_tasks, "_embedding_service", _FakeEmbeddings())
    monkeypatch.setattr(document_tasks, "_qdrant_service", _FakePipelineQdrant())
    graph_calls: list[dict[str, Any]] = []

    async def _record_graph(*args: Any, **kwargs: Any) -> dict[str, int]:
        graph_calls.append(kwargs)
        return {"entity_count": 0, "relation_count": 0}

    monkeypatch.setattr(document_tasks, "_run_document_graph_extraction_async", _record_graph)

    index_version = EVAL_VERSION if not persist_document_state else None
    await document_tasks._extract_and_store_document_pages_async(
        str(document.id),
        chunking_service=document_tasks._make_chunking_service(
            {"strategy": "token_recursive"}, index_version=index_version
        ),
        persist_document_state=persist_document_state,
    )

    # Production processing extracts graph facts; evaluation re-ingest must not.
    assert len(graph_calls) == (1 if persist_document_state else 0)
