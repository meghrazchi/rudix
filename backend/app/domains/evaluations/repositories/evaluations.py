import csv
import io
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvaluationDatasetStatus, EvaluationRunStatus
from app.models.evaluation import (
    EvaluationDatasetVersion,
    EvaluationQuestion,
    EvaluationResult,
    EvaluationRun,
    EvaluationSet,
)


class EvaluationRepository:
    async def create_evaluation_set(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None = None,
        owner_id: UUID | None = None,
        scope: dict | None = None,
    ) -> EvaluationSet:
        evaluation_set = EvaluationSet(
            organization_id=organization_id,
            name=name,
            description=description,
            owner_id=owner_id,
            scope_json=scope or {},
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

    async def get_evaluation_set_by_id(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
    ) -> EvaluationSet | None:
        result = await session.execute(
            select(EvaluationSet).where(EvaluationSet.id == evaluation_set_id)
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
            select(func.count(EvaluationSet.id)).where(
                EvaluationSet.organization_id == organization_id
            )
        )
        return int(result.scalar_one())

    async def update_evaluation_set(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        organization_id: UUID,
        name: str | None = None,
        description: str | None = None,
        scope: dict | None = None,
    ) -> EvaluationSet | None:
        result = await session.execute(
            select(EvaluationSet).where(
                EvaluationSet.id == evaluation_set_id,
                EvaluationSet.organization_id == organization_id,
            )
        )
        evaluation_set = result.scalar_one_or_none()
        if evaluation_set is None:
            return None
        if name is not None:
            evaluation_set.name = name
        if description is not None:
            evaluation_set.description = description
        if scope is not None:
            evaluation_set.scope_json = scope
        await session.flush()
        await session.refresh(evaluation_set)
        return evaluation_set

    async def delete_evaluation_set(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        organization_id: UUID,
    ) -> bool:
        result = await session.execute(
            select(EvaluationSet).where(
                EvaluationSet.id == evaluation_set_id,
                EvaluationSet.organization_id == organization_id,
            )
        )
        evaluation_set = result.scalar_one_or_none()
        if evaluation_set is None:
            return False
        await session.delete(evaluation_set)
        await session.flush()
        return True

    async def publish_evaluation_set(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        organization_id: UUID,
        published_by_id: UUID,
    ) -> EvaluationSet | None:
        result = await session.execute(
            select(EvaluationSet).where(
                EvaluationSet.id == evaluation_set_id,
                EvaluationSet.organization_id == organization_id,
            )
        )
        evaluation_set = result.scalar_one_or_none()
        if evaluation_set is None:
            return None

        question_count = await self.count_evaluation_questions(
            session, evaluation_set_id=evaluation_set_id
        )

        next_version = evaluation_set.version + (
            0 if evaluation_set.status == EvaluationDatasetStatus.draft else 1
        )
        if evaluation_set.status == EvaluationDatasetStatus.draft:
            next_version = evaluation_set.version

        evaluation_set.status = EvaluationDatasetStatus.published.value
        evaluation_set.version = next_version

        snapshot = {
            "name": evaluation_set.name,
            "description": evaluation_set.description,
            "question_count": question_count,
        }
        dataset_version = EvaluationDatasetVersion(
            evaluation_set_id=evaluation_set_id,
            version_number=next_version,
            question_count=question_count,
            published_by_id=published_by_id,
            published_at=datetime.now(UTC),
            snapshot=snapshot,
        )
        session.add(dataset_version)
        await session.flush()
        await session.refresh(evaluation_set)
        return evaluation_set

    async def duplicate_evaluation_set(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        organization_id: UUID,
        new_name: str,
        owner_id: UUID | None = None,
    ) -> EvaluationSet | None:
        result = await session.execute(
            select(EvaluationSet).where(
                EvaluationSet.id == evaluation_set_id,
                EvaluationSet.organization_id == organization_id,
            )
        )
        source = result.scalar_one_or_none()
        if source is None:
            return None

        new_set = EvaluationSet(
            organization_id=organization_id,
            name=new_name,
            description=source.description,
            status=EvaluationDatasetStatus.draft.value,
            version=1,
            owner_id=owner_id,
            scope_json=dict(source.scope_json or {}),
        )
        session.add(new_set)
        await session.flush()

        questions_result = await session.execute(
            select(EvaluationQuestion)
            .where(EvaluationQuestion.evaluation_set_id == evaluation_set_id)
            .order_by(EvaluationQuestion.created_at.asc())
        )
        for question in questions_result.scalars().all():
            new_question = EvaluationQuestion(
                evaluation_set_id=new_set.id,
                question=question.question,
                expected_answer=question.expected_answer,
                expected_document_id=question.expected_document_id,
                expected_page_number=question.expected_page_number,
                difficulty=question.difficulty,
                metadata_json=dict(question.metadata_json or {}),
            )
            session.add(new_question)

        await session.flush()
        await session.refresh(new_set)
        return new_set

    async def create_evaluation_question(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        question: str,
        expected_answer: str | None = None,
        expected_document_id: UUID | None = None,
        expected_page_number: int | None = None,
        difficulty: str | None = None,
        owner_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> EvaluationQuestion:
        evaluation_question = EvaluationQuestion(
            evaluation_set_id=evaluation_set_id,
            question=question,
            expected_answer=expected_answer,
            expected_document_id=expected_document_id,
            expected_page_number=expected_page_number,
            difficulty=difficulty,
            owner_id=owner_id,
            metadata_json=metadata or {},
        )
        session.add(evaluation_question)
        await session.flush()
        await session.refresh(evaluation_question)
        return evaluation_question

    async def get_evaluation_question(
        self,
        session: AsyncSession,
        *,
        evaluation_question_id: UUID,
        evaluation_set_id: UUID,
    ) -> EvaluationQuestion | None:
        result = await session.execute(
            select(EvaluationQuestion).where(
                EvaluationQuestion.id == evaluation_question_id,
                EvaluationQuestion.evaluation_set_id == evaluation_set_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_evaluation_question(
        self,
        session: AsyncSession,
        *,
        evaluation_question_id: UUID,
        evaluation_set_id: UUID,
        question: str | None = None,
        expected_answer: str | None = None,
        clear_expected_answer: bool = False,
        expected_document_id: UUID | None = None,
        clear_expected_document: bool = False,
        expected_page_number: int | None = None,
        clear_expected_page: bool = False,
        difficulty: str | None = None,
        clear_difficulty: bool = False,
        metadata: dict | None = None,
    ) -> EvaluationQuestion | None:
        result = await session.execute(
            select(EvaluationQuestion).where(
                EvaluationQuestion.id == evaluation_question_id,
                EvaluationQuestion.evaluation_set_id == evaluation_set_id,
            )
        )
        evaluation_question = result.scalar_one_or_none()
        if evaluation_question is None:
            return None
        if question is not None:
            evaluation_question.question = question
        if clear_expected_answer:
            evaluation_question.expected_answer = None
        elif expected_answer is not None:
            evaluation_question.expected_answer = expected_answer
        if clear_expected_document:
            evaluation_question.expected_document_id = None
        elif expected_document_id is not None:
            evaluation_question.expected_document_id = expected_document_id
        if clear_expected_page:
            evaluation_question.expected_page_number = None
        elif expected_page_number is not None:
            evaluation_question.expected_page_number = expected_page_number
        if clear_difficulty:
            evaluation_question.difficulty = None
        elif difficulty is not None:
            evaluation_question.difficulty = difficulty
        if metadata is not None:
            evaluation_question.metadata_json = metadata
        await session.flush()
        await session.refresh(evaluation_question)
        return evaluation_question

    async def delete_evaluation_question(
        self,
        session: AsyncSession,
        *,
        evaluation_question_id: UUID,
        evaluation_set_id: UUID,
    ) -> bool:
        result = await session.execute(
            select(EvaluationQuestion).where(
                EvaluationQuestion.id == evaluation_question_id,
                EvaluationQuestion.evaluation_set_id == evaluation_set_id,
            )
        )
        evaluation_question = result.scalar_one_or_none()
        if evaluation_question is None:
            return False
        await session.delete(evaluation_question)
        await session.flush()
        return True

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
            .order_by(EvaluationQuestion.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all_evaluation_questions(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
    ) -> list[EvaluationQuestion]:
        result = await session.execute(
            select(EvaluationQuestion)
            .where(EvaluationQuestion.evaluation_set_id == evaluation_set_id)
            .order_by(EvaluationQuestion.created_at.asc())
        )
        return list(result.scalars().all())

    async def count_evaluation_questions(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(EvaluationQuestion.id)).where(
                EvaluationQuestion.evaluation_set_id == evaluation_set_id
            )
        )
        return int(result.scalar_one())

    async def get_existing_question_texts(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
    ) -> set[str]:
        result = await session.execute(
            select(EvaluationQuestion.question).where(
                EvaluationQuestion.evaluation_set_id == evaluation_set_id
            )
        )
        return {row[0].strip().lower() for row in result.all()}

    async def bulk_import_questions(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        raw_data: str,
        fmt: str,
        skip_duplicates: bool,
    ) -> tuple[int, int, list[str]]:
        rows: list[dict] = []
        errors: list[str] = []

        if fmt == "json":
            try:
                parsed = json.loads(raw_data)
                rows = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError as exc:
                return 0, 0, [f"JSON parse error: {exc}"]
        else:
            reader = csv.DictReader(io.StringIO(raw_data))
            for i, row in enumerate(reader, start=2):
                rows.append({k: (v or "").strip() for k, v in row.items()})
                if i > 1001:
                    errors.append("Import limited to 1000 rows per request")
                    break

        existing_texts: set[str] = set()
        if skip_duplicates:
            existing_texts = await self.get_existing_question_texts(
                session, evaluation_set_id=evaluation_set_id
            )

        imported = 0
        skipped = 0
        for idx, row in enumerate(rows):
            question_text = str(row.get("question", "")).strip()
            if not question_text:
                errors.append(f"Row {idx + 1}: question is required")
                continue

            if skip_duplicates and question_text.lower() in existing_texts:
                skipped += 1
                continue

            raw_answer = row.get("expected_answer") or row.get("answer")
            expected_answer = str(raw_answer).strip() if raw_answer else None

            raw_page = row.get("expected_page_number") or row.get("page")
            expected_page: int | None = None
            if raw_page:
                try:
                    expected_page = int(str(raw_page).strip())
                    if expected_page < 1:
                        expected_page = None
                except (ValueError, TypeError):
                    pass

            raw_difficulty = row.get("difficulty")
            difficulty: str | None = None
            if raw_difficulty and str(raw_difficulty).strip().lower() in {"easy", "medium", "hard"}:
                difficulty = str(raw_difficulty).strip().lower()

            raw_tags = row.get("tags")
            tags: list[str] = []
            if raw_tags:
                tags = [
                    t.strip() for t in str(raw_tags).split(",") if t.strip()
                ]

            eq = EvaluationQuestion(
                evaluation_set_id=evaluation_set_id,
                question=question_text,
                expected_answer=expected_answer,
                expected_page_number=expected_page,
                difficulty=difficulty,
                metadata_json={"tags": tags} if tags else {},
            )
            session.add(eq)
            existing_texts.add(question_text.lower())
            imported += 1

        if imported > 0:
            await session.flush()

        return imported, skipped, errors

    async def list_dataset_versions(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
    ) -> list[EvaluationDatasetVersion]:
        result = await session.execute(
            select(EvaluationDatasetVersion)
            .where(EvaluationDatasetVersion.evaluation_set_id == evaluation_set_id)
            .order_by(EvaluationDatasetVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def validate_dataset(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
        organization_id: UUID,
    ) -> list[dict]:
        from app.models.document import Document
        from app.models.enums import DocumentStatus

        questions_result = await session.execute(
            select(EvaluationQuestion).where(
                EvaluationQuestion.evaluation_set_id == evaluation_set_id
            )
        )
        questions = list(questions_result.scalars().all())
        issues: list[dict] = []
        seen_texts: set[str] = set()

        for question in questions:
            preview = question.question[:80]
            normalized = question.question.strip().lower()

            if normalized in seen_texts:
                issues.append(
                    {
                        "evaluation_question_id": str(question.id),
                        "question_preview": preview,
                        "issue_type": "duplicate",
                        "detail": "Duplicate question text detected within the dataset",
                    }
                )
            else:
                seen_texts.add(normalized)

            if question.expected_document_id is not None:
                doc_result = await session.execute(
                    select(Document).where(Document.id == question.expected_document_id)
                )
                doc = doc_result.scalar_one_or_none()
                if doc is None or doc.status in (
                    DocumentStatus.deleted.value,
                    DocumentStatus.delete_requested.value,
                    DocumentStatus.blocked.value,
                ):
                    issues.append(
                        {
                            "evaluation_question_id": str(question.id),
                            "question_preview": preview,
                            "issue_type": "deleted_source",
                            "detail": "Expected document is deleted or inaccessible",
                        }
                    )
                elif doc.organization_id != organization_id:
                    issues.append(
                        {
                            "evaluation_question_id": str(question.id),
                            "question_preview": preview,
                            "issue_type": "inaccessible_document",
                            "detail": "Expected document belongs to a different organization",
                        }
                    )

        return issues

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

    async def count_active_runs_for_set(
        self,
        session: AsyncSession,
        *,
        evaluation_set_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(EvaluationRun.id)).where(
                EvaluationRun.evaluation_set_id == evaluation_set_id,
                EvaluationRun.status.in_(
                    [EvaluationRunStatus.queued.value, EvaluationRunStatus.running.value]
                ),
            )
        )
        return int(result.scalar_one())

    async def get_evaluation_run(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
    ) -> EvaluationRun | None:
        result = await session.execute(
            select(EvaluationRun).where(EvaluationRun.id == evaluation_run_id)
        )
        return result.scalar_one_or_none()

    async def get_evaluation_run_for_organization(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
        organization_id: UUID,
    ) -> EvaluationRun | None:
        result = await session.execute(
            select(EvaluationRun)
            .join(EvaluationSet, EvaluationSet.id == EvaluationRun.evaluation_set_id)
            .where(
                EvaluationRun.id == evaluation_run_id,
                EvaluationSet.organization_id == organization_id,
            )
        )
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
        result = await session.execute(
            select(EvaluationRun).where(EvaluationRun.id == evaluation_run_id)
        )
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

    async def update_evaluation_run_config(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
        config_patch: dict[str, object],
    ) -> EvaluationRun | None:
        result = await session.execute(
            select(EvaluationRun).where(EvaluationRun.id == evaluation_run_id)
        )
        evaluation_run = result.scalar_one_or_none()
        if evaluation_run is None:
            return None

        current_config = evaluation_run.config if isinstance(evaluation_run.config, dict) else {}
        merged_config = dict(current_config)
        merged_config.update(config_patch)
        evaluation_run.config = merged_config
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

    async def list_evaluation_results_for_run(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[tuple[EvaluationResult, EvaluationQuestion]]:
        result = await session.execute(
            select(EvaluationResult, EvaluationQuestion)
            .join(
                EvaluationQuestion, EvaluationQuestion.id == EvaluationResult.evaluation_question_id
            )
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def count_evaluation_results_for_run(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(EvaluationResult.id)).where(
                EvaluationResult.evaluation_run_id == evaluation_run_id
            )
        )
        return int(result.scalar_one())

    async def delete_evaluation_results_for_run(
        self,
        session: AsyncSession,
        *,
        evaluation_run_id: UUID,
    ) -> int:
        result = await session.execute(
            delete(EvaluationResult).where(EvaluationResult.evaluation_run_id == evaluation_run_id)
        )
        return int(result.rowcount or 0)
