from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvaluationRunStatus
from app.models.evaluation import EvaluationQuestion, EvaluationResult, EvaluationRun, EvaluationSet


class EvaluationRepository:
    async def create_evaluation_set(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None = None,
    ) -> EvaluationSet:
        evaluation_set = EvaluationSet(
            organization_id=organization_id,
            name=name,
            description=description,
        )
        session.add(evaluation_set)
        await session.flush()
        await session.refresh(evaluation_set)
        return evaluation_set

    async def create_evaluation_question(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        question: str,
        expected_answer: str | None = None,
        expected_document_id: UUID | None = None,
        expected_page_number: int | None = None,
        metadata: dict | None = None,
    ) -> EvaluationQuestion:
        evaluation_question = EvaluationQuestion(
            evaluation_set_id=evaluation_set_id,
            question=question,
            expected_answer=expected_answer,
            expected_document_id=expected_document_id,
            expected_page_number=expected_page_number,
            metadata_json=metadata or {},
        )
        session.add(evaluation_question)
        await session.flush()
        await session.refresh(evaluation_question)
        return evaluation_question

    async def create_evaluation_run(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        status: str = EvaluationRunStatus.queued.value,
        config: dict | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> EvaluationRun:
        evaluation_run = EvaluationRun(
            evaluation_set_id=evaluation_set_id,
            status=status,
            config=config or {},
            started_at=started_at,
            completed_at=completed_at,
        )
        session.add(evaluation_run)
        await session.flush()
        await session.refresh(evaluation_run)
        return evaluation_run

    async def get_evaluation_run(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
    ) -> EvaluationRun | None:
        result = await session.execute(select(EvaluationRun).where(EvaluationRun.id == evaluation_run_id))
        return result.scalar_one_or_none()

    async def create_evaluation_result(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
        evaluation_question_id: UUID,
        generated_answer: str | None = None,
        retrieval_score: float | None = None,
        faithfulness_score: float | None = None,
        citation_accuracy_score: float | None = None,
        answer_relevance_score: float | None = None,
        latency_ms: int | None = None,
        details: dict | None = None,
    ) -> EvaluationResult:
        evaluation_result = EvaluationResult(
            evaluation_run_id=evaluation_run_id,
            evaluation_question_id=evaluation_question_id,
            generated_answer=generated_answer,
            retrieval_score=retrieval_score,
            faithfulness_score=faithfulness_score,
            citation_accuracy_score=citation_accuracy_score,
            answer_relevance_score=answer_relevance_score,
            latency_ms=latency_ms,
            details=details or {},
        )
        session.add(evaluation_result)
        await session.flush()
        await session.refresh(evaluation_result)
        return evaluation_result
