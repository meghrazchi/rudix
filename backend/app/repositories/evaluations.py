from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
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

    async def get_evaluation_set(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        organization_id: UUID,
    ) -> EvaluationSet | None:
        result = await session.execute(
            select(EvaluationSet).where(
                EvaluationSet.id == evaluation_set_id,
                EvaluationSet.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_evaluation_sets(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[EvaluationSet]:
        result = await session.execute(
            select(EvaluationSet)
            .where(EvaluationSet.organization_id == organization_id)
            .order_by(EvaluationSet.created_at.desc(), EvaluationSet.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_evaluation_sets(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(EvaluationSet.id)).where(EvaluationSet.organization_id == organization_id)
        )
        return int(result.scalar_one())

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

    async def list_evaluation_questions(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[EvaluationQuestion]:
        result = await session.execute(
            select(EvaluationQuestion)
            .where(EvaluationQuestion.evaluation_set_id == evaluation_set_id)
            .order_by(EvaluationQuestion.created_at.asc(), EvaluationQuestion.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_evaluation_questions(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(EvaluationQuestion.id)).where(EvaluationQuestion.evaluation_set_id == evaluation_set_id)
        )
        return int(result.scalar_one())

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

    async def update_evaluation_run_status(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
        status: str,
        mark_started: bool = False,
        mark_completed: bool = False,
    ) -> EvaluationRun | None:
        result = await session.execute(select(EvaluationRun).where(EvaluationRun.id == evaluation_run_id))
        evaluation_run = result.scalar_one_or_none()
        if evaluation_run is None:
            return None

        evaluation_run.status = status
        if mark_started and evaluation_run.started_at is None:
            evaluation_run.started_at = datetime.now(UTC)
        if mark_completed:
            evaluation_run.completed_at = datetime.now(UTC)

        await session.flush()
        await session.refresh(evaluation_run)
        return evaluation_run

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
