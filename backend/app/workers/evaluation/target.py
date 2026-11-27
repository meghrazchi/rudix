"""One chunking target: prepare its corpus, evaluate the questions, clean up (R06-12).

Questions run inside an ``asyncio.Semaphore`` of ``EVALUATION_MAX_CONCURRENT_QUESTIONS``
(1 = one after the other, the pre-0.6.0 behaviour). The LLM answer and judge calls happen
inside the bound. Results of the first target are written in question order, each in its
own short session, while the question still holds its slot; no session is shared between
questions or held across a provider call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import log_evaluation_event
from app.core.metrics_workers import record_evaluation_question_in_flight
from app.domains.ai.profile.schemas import ResolvedTaskProfile
from app.domains.evaluations.services.evaluation_metrics_service import (
    EvaluationQuestionMetrics,
)
from app.models.evaluation import EvaluationQuestion
from app.workers.base_task import TransientTaskError
from app.workers.evaluation import facade
from app.workers.evaluation.collection import evaluation_collection, reingest_embedding_model
from app.workers.evaluation.comparison import _build_target_summary, _derive_target_score
from app.workers.evaluation.config import ChunkingComparisonTarget, EvaluationRunConfig
from app.workers.evaluation.corpus import _build_target_index_version, _cleanup_target_index_async
from app.workers.evaluation.question import EvaluationQuestionComputation
from app.workers.evaluation_index_cleanup import is_eval_index_version


@dataclass
class RunContext:
    """Run-level inputs shared by every target (plain values, no ORM session)."""

    parsed_run_id: UUID
    evaluation_run_id: str
    owner_organization_id: UUID
    request_id: str | None
    organization_id: str | None
    user_id: str | None
    run_config: EvaluationRunConfig
    llm_service: Any
    questions: list[EvaluationQuestion]
    document_ids: list[UUID]
    prompt_template_content: str | None = None
    prompt_template_metadata: dict[str, Any] | None = None
    resolved_profile: ResolvedTaskProfile | None = None
    cleanup_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def log_organization_id(self) -> str:
        return self.organization_id or str(self.owner_organization_id)


@dataclass
class TargetOutcome:
    summary: dict[str, Any]
    question_scores: dict[str, float | None]
    success_count: int
    failure_count: int


def retrieval_service_for(index_version: str | None) -> Any | None:
    """A search bound to the evaluation collection for eval- versions, else None.

    None means the facade's ``_query_retrieval_service`` (the production alias or
    collection): baseline targets read the production index version there.

    The query is embedded with the model the re-ingest used (the ingestion embedding
    service, ``OPENAI_EMBEDDING_MODEL``), not the active generation's: in alias mode the two
    may differ with the same dimension, and the vectors would not be comparable.
    """
    collection = evaluation_collection()
    if collection is None or not is_eval_index_version(index_version):
        return None
    return facade().QueryRetrievalService(
        qdrant_collection=collection,
        embedding_model=reingest_embedding_model(),
        vector_size=settings.qdrant_vector_size,
    )


def _failed_computation(
    ctx: RunContext, question: EvaluationQuestion, exc: Exception, started: float
) -> EvaluationQuestionComputation:
    failed_metrics = facade()._evaluation_metrics_service.score_question(
        expected_document_id=question.expected_document_id,
        expected_page_number=question.expected_page_number,
        expected_answer=question.expected_answer,
        generated_answer="",
        not_found=True,
        retrieved_chunks=[],
        selected_chunk_count=0,
        citation_count=0,
        citation_accuracy_score=None,
        latency_ms=int((perf_counter() - started) * 1000),
        cost_usd=0.0,
        token_input_count=0,
        token_output_count=0,
        options=ctx.run_config.metric_options,
        judge_scores=None,
        judge_error=exc.__class__.__name__,
    )
    return EvaluationQuestionComputation(
        generated_answer="",
        retrieval_score=None,
        faithfulness_score=None,
        citation_accuracy_score=None,
        answer_relevance_score=None,
        metrics=failed_metrics,
        latency_ms=failed_metrics.latency_ms,
        details={
            "status": "failed",
            "question": question.question,
            "expected_answer": question.expected_answer,
            "expected_document_id": (
                str(question.expected_document_id)
                if question.expected_document_id is not None
                else None
            ),
            "expected_page_number": question.expected_page_number,
            "metrics": failed_metrics.as_dict(),
            "error": str(exc),
            "error_type": exc.__class__.__name__,
        },
    )


async def _evaluate_one(
    ctx: RunContext,
    *,
    target: ChunkingComparisonTarget,
    index_version: str,
    question: EvaluationQuestion,
    retrieval_service: Any | None,
    offload_blocking: bool,
) -> tuple[EvaluationQuestionComputation, bool]:
    started = perf_counter()
    common: dict[str, Any] = {
        "organization_id": ctx.log_organization_id,
        "user_id": ctx.user_id,
        "job_id": ctx.evaluation_run_id,
        "request_id": ctx.request_id,
        "question_id": str(question.id),
        "target_label": target.label,
        "index_version": index_version,
    }
    try:
        computed = await facade()._evaluate_question_pipeline_async(
            question_text=question.question,
            expected_answer=question.expected_answer,
            expected_document_id=question.expected_document_id,
            expected_page_number=question.expected_page_number,
            organization_id=ctx.owner_organization_id,
            config=ctx.run_config,
            llm_service=ctx.llm_service,
            index_version=index_version,
            prompt_template_content=ctx.prompt_template_content,
            prompt_template_metadata=ctx.prompt_template_metadata,
            resolved_profile=ctx.resolved_profile,
            retrieval_service=retrieval_service,
            offload_blocking=offload_blocking,
        )
    except Exception as exc:
        computed = _failed_computation(ctx, question, exc, started)
        ok = False
        log_evaluation_event(
            event="evaluation.question.failed", error=exc.__class__.__name__, **common
        )
    else:
        ok = True
        log_evaluation_event(
            event="evaluation.question.completed",
            not_found=computed.details.get("not_found"),
            confidence_score=computed.answer_relevance_score,
            **common,
        )
    computed.details["chunking_target"] = {
        "label": target.label,
        "chunking_strategy": target.chunking_strategy,
        "chunking_profile_id": target.chunking_profile_id,
        "profile_version": target.profile_version,
        "profile_source": target.profile_source,
        "index_version": index_version,
    }
    return computed, ok


async def _persist_result(
    ctx: RunContext, question: EvaluationQuestion, computed: EvaluationQuestionComputation
) -> None:
    f = facade()
    async with f.SessionLocal() as session:
        try:
            await f._evaluation_repository.create_evaluation_result(
                session,
                evaluation_run_id=ctx.parsed_run_id,
                evaluation_question_id=question.id,
                generated_answer=computed.generated_answer or None,
                retrieval_score=computed.retrieval_score,
                faithfulness_score=computed.faithfulness_score,
                citation_accuracy_score=computed.citation_accuracy_score,
                answer_relevance_score=computed.answer_relevance_score,
                latency_ms=computed.latency_ms,
                details=computed.details,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to persist evaluation result for question: {question.id}"
            ) from exc


async def _evaluate_questions(
    ctx: RunContext,
    *,
    target: ChunkingComparisonTarget,
    index_version: str,
    persist: bool,
) -> list[tuple[EvaluationQuestionComputation, bool]]:
    """Evaluate every question within the bound; returns results in question order."""
    bound = settings.evaluation_max_concurrent_questions
    semaphore = asyncio.Semaphore(bound)
    write_lock = asyncio.Lock()
    retrieval_service = retrieval_service_for(index_version)
    results: dict[int, tuple[EvaluationQuestionComputation, bool]] = {}
    written = 0

    async def flush_in_order() -> None:
        nonlocal written
        async with write_lock:
            while written in results:
                if persist:
                    await _persist_result(ctx, ctx.questions[written], results[written][0])
                written += 1

    async def run_question(position: int, question: EvaluationQuestion) -> None:
        async with semaphore:
            record_evaluation_question_in_flight(1)
            try:
                results[position] = await _evaluate_one(
                    ctx,
                    target=target,
                    index_version=index_version,
                    question=question,
                    retrieval_service=retrieval_service,
                    offload_blocking=bound > 1,
                )
            finally:
                record_evaluation_question_in_flight(-1)
            await flush_in_order()

    tasks = [
        asyncio.create_task(run_question(position, question))
        for position, question in enumerate(ctx.questions)
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return [results[position] for position in range(len(ctx.questions))]


async def evaluate_target(
    ctx: RunContext, *, target_index: int, target: ChunkingComparisonTarget
) -> TargetOutcome:
    """Prepare, evaluate and summarise one target; its eval index is always cleaned up."""
    eval_index_version = (
        _build_target_index_version(evaluation_run_id=ctx.parsed_run_id, target_index=target_index)
        if target.chunking_profile_config is not None
        else None
    )
    prepared_index_version: str | None = None
    try:
        index_version, corpus_stats = await facade()._prepare_chunking_target_corpus_async(
            evaluation_run_id=ctx.parsed_run_id,
            target_index=target_index,
            target=target,
            document_ids=ctx.document_ids,
            request_id=ctx.request_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
        )
        prepared_index_version = index_version
        results = await _evaluate_questions(
            ctx, target=target, index_version=index_version, persist=target_index == 0
        )
        successful_metrics: list[EvaluationQuestionMetrics] = [
            computed.metrics for computed, ok in results if ok
        ]
        success_count = len(successful_metrics)
        question_scores = {
            str(question.id): _derive_target_score(computed.metrics.as_dict())
            for question, (computed, _ok) in zip(ctx.questions, results, strict=True)
        }
        summary = _build_target_summary(
            target=target,
            index_version=index_version,
            corpus_stats=corpus_stats,
            metrics=successful_metrics,
            total_questions=len(ctx.questions),
            success_count=success_count,
            failure_count=len(results) - success_count,
        )
        return TargetOutcome(
            summary=summary,
            question_scores=question_scores,
            success_count=success_count,
            failure_count=len(results) - success_count,
        )
    finally:
        cleanup_version = prepared_index_version or eval_index_version
        if cleanup_version is not None and is_eval_index_version(cleanup_version):
            ctx.cleanup_results.append(
                await _cleanup_target_index_async(
                    organization_id=ctx.owner_organization_id,
                    document_ids=ctx.document_ids,
                    index_version=cleanup_version,
                    evaluation_run_id=ctx.evaluation_run_id,
                    request_id=ctx.request_id,
                    user_id=ctx.user_id,
                )
            )
