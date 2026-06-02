from __future__ import annotations

import os
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
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

from app.core.config import settings
from app.domains.chat.services.llm_service import ParsedCitation
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.models.enums import DocumentStatus, EvaluationRunStatus, OrganizationRole
from app.models.evaluation import EvaluationResult, EvaluationRun
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User
from app.workers import evaluation_tasks


class FakeQueryRetrievalService:
    def __init__(
        self,
        outcomes: list[list[RetrievedCandidate] | Exception] | None = None,
        *,
        outcomes_by_index_version: (
            dict[str | None, list[RetrievedCandidate] | Exception] | None
        ) = None,
    ) -> None:
        self.embedding_model = settings.openai_embedding_model
        self._outcomes = outcomes or []
        self._outcomes_by_index_version = outcomes_by_index_version or {}
        self._retrieve_calls = 0

    async def embed_query(
        self,
        *,
        question: str,
        openai_client: object | None = None,
    ) -> tuple[list[float], int]:
        del question, openai_client
        return [0.01] * settings.qdrant_vector_size, 9

    def retrieve_candidates(
        self,
        *,
        query_vector: list[float],
        organization_id: UUID,
        document_ids: list[UUID],
        initial_top_k: int,
        index_version: str | None = None,
        qdrant_client: object | None = None,
    ) -> list[RetrievedCandidate]:
        del query_vector, organization_id, document_ids, initial_top_k, qdrant_client
        if self._outcomes_by_index_version:
            outcome = self._outcomes_by_index_version.get(index_version, [])
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        if self._retrieve_calls >= len(self._outcomes):
            return []
        outcome = self._outcomes[self._retrieve_calls]
        self._retrieve_calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeLLMService:
    def __init__(self, *, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.openai_llm_model

    async def generate_answer(
        self,
        *,
        prompt: str,
        openai_client: object,
    ) -> object:
        del prompt, openai_client
        return type(
            "FakeLLMAnswerResult",
            (),
            {
                "answer": "Employees receive twenty days of annual leave.",
                "not_found": False,
                "citations": [
                    ParsedCitation(
                        document_id="00000000-0000-0000-0000-000000000000",
                        chunk_id="00000000-0000-0000-0000-000000000000",
                    )
                ],
                "model_name": self.model_name,
                "prompt_tokens": 31,
                "completion_tokens": 14,
                "total_tokens": 45,
                "approximate_cost_usd": Decimal("0.000012"),
                "latency_ms": 11,
                "retry_count": 0,
                "used_fallback_parser": False,
            },
        )()


async def _seed_evaluation_run(
    db_session: AsyncSession,
    *,
    question_texts: list[str],
    selected_document_ids: list[str],
) -> tuple[str, UUID, UUID, UUID]:
    organization = Organization(name="Eval Worker Org", slug=f"eval-worker-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"eval-worker-user-{uuid4().hex[:8]}",
        email=f"eval-worker-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db_session.flush()

    document_repository = DocumentRepository()
    document = await document_repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=user.id,
        filename="policy.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{uuid4().hex}.pdf",
        status=DocumentStatus.indexed.value,
    )
    chunk = await document_repository.create_document_chunk(
        db_session,
        document_id=document.id,
        page_number=1,
        chunk_index=0,
        text="Employees receive twenty days of annual leave.",
        token_count=60,
        embedding_model=settings.openai_embedding_model,
        index_version=settings.document_index_version,
        qdrant_point_id=f"{document.id}:{settings.document_index_version}:0",
    )

    evaluation_repository = EvaluationRepository()
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Worker Eval Set",
    )
    for question_text in question_texts:
        await evaluation_repository.create_evaluation_question(
            db_session,
            evaluation_set_id=evaluation_set.id,
            question=question_text,
            expected_answer="Employees receive twenty days of annual leave.",
            expected_document_id=document.id,
            expected_page_number=1,
        )

    evaluation_run = await evaluation_repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.queued.value,
        config={
            "top_k": 3,
            "rerank": True,
            "model_name": settings.openai_llm_model,
            "selected_document_ids": selected_document_ids,
            "metric_options": {"faithfulness": True},
        },
    )
    await db_session.commit()
    return str(evaluation_run.id), organization.id, document.id, chunk.id


@pytest.mark.asyncio
async def test_evaluation_worker_persists_results_and_continues_on_question_failure(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, _, document_id, chunk_id = await _seed_evaluation_run(
        db_session,
        question_texts=["Question success", "Question failure"],
        selected_document_ids=[],
    )

    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(evaluation_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(evaluation_tasks, "LLMService", FakeLLMService)
    monkeypatch.setattr(
        evaluation_tasks,
        "_query_retrieval_service",
        FakeQueryRetrievalService(
            outcomes=[
                [
                    RetrievedCandidate(
                        document_id=document_id,
                        chunk_id=chunk_id,
                        filename="policy.pdf",
                        page_number=1,
                        text="Employees receive twenty days of annual leave.",
                        similarity_score=0.93,
                    )
                ],
                RuntimeError("qdrant timeout"),
            ]
        ),
    )

    result = await evaluation_tasks._run_evaluation_async(run_id)
    assert result["question_total_count"] == 2
    assert result["question_success_count"] == 1
    assert result["question_failure_count"] == 1
    assert result["all_questions_failed"] is False

    rows = list(
        (
            await db_session.execute(
                select(EvaluationResult).where(EvaluationResult.evaluation_run_id == UUID(run_id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    completed = next(row for row in rows if row.details.get("status") == "completed")
    failed = next(row for row in rows if row.details.get("status") == "failed")

    assert completed.generated_answer == "Employees receive twenty days of annual leave."
    assert completed.details["retrieval_count"] == 1
    assert completed.details["selected_count"] == 1
    assert completed.details["embedding_model"] == settings.openai_embedding_model
    assert completed.details["citations"]
    assert completed.details["retrieved_chunks"][0]["document_id"] == str(document_id)
    assert completed.details["metrics"]["retrieval_hit_rate"] == 1.0
    assert completed.details["metrics"]["context_precision"] == 1.0
    assert completed.details["metrics"]["context_recall"] == 1.0

    assert failed.generated_answer is None
    assert failed.details["error_type"] == "RuntimeError"
    assert failed.details["error"] == "qdrant timeout"
    assert failed.details["question"] == "Question failure"
    assert failed.details["metrics"]["judge_error"] == "RuntimeError"

    run_row = (
        await db_session.execute(select(EvaluationRun).where(EvaluationRun.id == UUID(run_id)))
    ).scalar_one()
    summary = run_row.config["metrics_summary"]
    assert summary["question_total_count"] == 2
    assert summary["question_success_count"] == 1
    assert summary["question_failure_count"] == 1
    assert summary["retrieval_hit_rate"] == 1.0
    assert summary["context_precision"] == 1.0
    assert summary["context_recall"] == 1.0


@pytest.mark.asyncio
async def test_evaluation_worker_marks_failed_when_all_questions_fail(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, _, _, _ = await _seed_evaluation_run(
        db_session,
        question_texts=["Question failure"],
        selected_document_ids=[],
    )

    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(evaluation_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(evaluation_tasks, "LLMService", FakeLLMService)
    monkeypatch.setattr(
        evaluation_tasks,
        "_query_retrieval_service",
        FakeQueryRetrievalService(outcomes=[RuntimeError("retrieval unavailable")]),
    )

    result = await evaluation_tasks._run_evaluation_async(run_id)
    assert result["question_total_count"] == 1
    assert result["question_success_count"] == 0
    assert result["question_failure_count"] == 1
    assert result["all_questions_failed"] is True
    assert result["metrics_summary"]["question_success_count"] == 0
    assert result["metrics_summary"]["question_failure_count"] == 1

    rows = list(
        (
            await db_session.execute(
                select(EvaluationResult).where(EvaluationResult.evaluation_run_id == UUID(run_id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].details["status"] == "failed"
    assert rows[0].details["error"] == "retrieval unavailable"

    run_row = (
        await db_session.execute(select(EvaluationRun).where(EvaluationRun.id == UUID(run_id)))
    ).scalar_one()
    summary = run_row.config["metrics_summary"]
    assert summary["question_total_count"] == 1
    assert summary["question_success_count"] == 0
    assert summary["question_failure_count"] == 1
    assert summary["retrieval_hit_rate"] is None


@pytest.mark.asyncio
async def test_evaluation_worker_audit_helper_writes_log(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, organization_id, _, _ = await _seed_evaluation_run(
        db_session,
        question_texts=["Question success"],
        selected_document_ids=[],
    )

    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(evaluation_tasks, "SessionLocal", session_factory)

    await evaluation_tasks._record_worker_audit_async(
        action="evaluation.run.completed",
        resource_type="evaluation_run",
        resource_id=run_id,
        organization_id=str(organization_id),
        user_id=None,
        request_id="req-eval-task-audit",
        metadata={
            "status": EvaluationRunStatus.completed.value,
            "question_total_count": 1,
            "question_success_count": 1,
            "question_failure_count": 0,
        },
    )
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "evaluation.run.completed"
    assert audit_logs[0].resource_id == UUID(run_id)
    assert audit_logs[0].metadata_json["question_total_count"] == 1
    assert audit_logs[0].metadata_json["request_id"] == "req-eval-task-audit"


@pytest.mark.asyncio
async def test_evaluation_worker_stores_chunking_comparison_summary(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, _, document_id, chunk_id = await _seed_evaluation_run(
        db_session,
        question_texts=["Question success"],
        selected_document_ids=[],
    )

    run_row = (
        await db_session.execute(select(EvaluationRun).where(EvaluationRun.id == UUID(run_id)))
    ).scalar_one()
    run_row.config = {
        **run_row.config,
        "comparison_targets": [
            {
                "label": "Baseline profile",
                "chunking_profile_id": "profile-a",
                "chunking_profile_config": {"strategy": "token_recursive"},
                "chunking_strategy": "token_recursive",
                "profile_version": "cfg-baseline",
                "profile_source": "organization_profile",
            },
            {
                "label": "Candidate profile",
                "chunking_profile_id": "profile-b",
                "chunking_profile_config": {"strategy": "paragraph_recursive"},
                "chunking_strategy": "paragraph_recursive",
                "profile_version": "cfg-candidate",
                "profile_source": "organization_profile",
            },
        ],
        "regression_thresholds": {
            "retrieval_hit_rate_min": 0.5,
            "citation_accuracy_score_min": 0.5,
        },
    }
    await db_session.commit()

    session_factory = async_sessionmaker(
        bind=db_session.bind, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(evaluation_tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(evaluation_tasks, "LLMService", FakeLLMService)

    async def fake_prepare_chunking_target_corpus_async(
        *,
        evaluation_run_id: UUID,
        target_index: int,
        target: evaluation_tasks.ChunkingComparisonTarget,
        document_ids: list[UUID],
        request_id: str | None,
        organization_id: str | None,
        user_id: str | None,
    ) -> tuple[str, evaluation_tasks.ChunkingCorpusStats]:
        del evaluation_run_id, target, document_ids, request_id, organization_id, user_id
        return (
            f"eval-target-{target_index + 1}",
            evaluation_tasks.ChunkingCorpusStats(
                chunk_count_total=4 + target_index,
                chunk_tokens_average=120.0 + target_index,
                chunk_tokens_variance=12.5 + target_index,
                chunk_tokens_min=80,
                chunk_tokens_max=180,
                document_type_breakdown={"pdf": 1},
                language_breakdown={"en": 1},
                ocr_breakdown={"native_text": 1},
            ),
        )

    monkeypatch.setattr(
        evaluation_tasks,
        "_prepare_chunking_target_corpus_async",
        fake_prepare_chunking_target_corpus_async,
    )
    monkeypatch.setattr(
        evaluation_tasks,
        "_query_retrieval_service",
        FakeQueryRetrievalService(
            outcomes_by_index_version={
                "eval-target-1": [
                    RetrievedCandidate(
                        document_id=document_id,
                        chunk_id=chunk_id,
                        filename="policy.pdf",
                        page_number=1,
                        text="Employees receive twenty days of annual leave.",
                        similarity_score=0.93,
                    )
                ],
                "eval-target-2": [],
            },
        ),
    )

    result = await evaluation_tasks._run_evaluation_async(run_id)
    assert result["question_total_count"] == 1
    assert result["question_success_count"] == 1
    assert result["question_failure_count"] == 0

    refreshed_run = (
        await db_session.execute(select(EvaluationRun).where(EvaluationRun.id == UUID(run_id)))
    ).scalar_one()
    await db_session.refresh(refreshed_run)
    summary = refreshed_run.config["metrics_summary"]
    assert summary["comparison"]["baseline_label"] == "Baseline profile"
    assert summary["comparison"]["latest_label"] == "Candidate profile"
    assert len(summary["comparison_targets"]) == 2
    assert summary["comparison_targets"][0]["chunk_count_total"] == 4
    assert summary["comparison_targets"][1]["regression_failed"] is True
    assert summary["best_by_document_type"]["pdf"]["label"] == "Baseline profile"
    assert summary["best_by_use_case"]["unlabeled"]["label"] == "Baseline profile"
    assert summary["regression_failed"] is True
