from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import asdict, dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import log_evaluation_event
from app.db.session import SessionLocal
from app.models.enums import EvaluationRunStatus
from app.repositories.evaluations import EvaluationRepository
from app.services.audit_service import AuditLogService
from app.services.citation_service import CitationContextChunk, CitationService
from app.services.confidence_service import ConfidenceChunkSignal, ConfidenceService
from app.services.evaluation_metrics_service import (
    EvaluationJudgeScores,
    EvaluationMetricOptions,
    EvaluationMetricsService,
    EvaluationQuestionMetrics,
    RetrievedMetricChunk,
)
from app.services.llm_service import LLMService, PermanentLLMServiceError, TransientLLMServiceError
from app.services.prompt_service import PromptContextChunk, PromptService
from app.services.query_retrieval_service import QueryRetrievalService, RetrievedCandidate
from app.services.rerank_service import RerankCandidate, RerankService
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.status_tracking import get_evaluation_status, set_evaluation_status

_evaluation_repository = EvaluationRepository()
_query_retrieval_service = QueryRetrievalService()
_rerank_service = RerankService()
_prompt_service = PromptService()
_citation_service = CitationService()
_confidence_service = ConfidenceService()
_evaluation_metrics_service = EvaluationMetricsService()
_audit_log_service = AuditLogService()
_worker_loop: asyncio.AbstractEventLoop | None = None
_openai_client: AsyncOpenAI | None = None
_NOT_FOUND_ANSWER = "I could not find this information in the uploaded documents."


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    rerank_score: float | None = None
    rerank_rank: int | None = None


@dataclass(frozen=True)
class EvaluationRunConfig:
    top_k: int
    rerank: bool
    model_name: str
    selected_document_ids: list[UUID]
    metric_options: EvaluationMetricOptions


@dataclass(frozen=True)
class EvaluationQuestionComputation:
    generated_answer: str
    retrieval_score: float | None
    faithfulness_score: float | None
    citation_accuracy_score: float | None
    answer_relevance_score: float | None
    metrics: EvaluationQuestionMetrics
    latency_ms: int
    details: dict[str, Any]


def _parse_uuid(value: str) -> UUID:
    return UUID(value)


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)


def _parse_optional_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def _record_worker_audit_async(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    organization_uuid = _parse_optional_uuid(organization_id)
    if organization_uuid is None:
        return
    user_uuid = _parse_optional_uuid(user_id)
    parsed_resource_id = _parse_optional_uuid(resource_id)
    try:
        async with SessionLocal() as audit_session:
            wrote_audit = await _audit_log_service.record(
                audit_session,
                organization_id=organization_uuid,
                user_id=user_uuid,
                action=action,
                resource_type=resource_type,
                resource_id=parsed_resource_id,
                request_id=request_id,
                metadata=metadata or {},
            )
            if wrote_audit:
                await audit_session.commit()
    except Exception:
        return


def _record_worker_audit(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    _run(
        _record_worker_audit_async(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            metadata=metadata,
        )
    )


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        if settings.openai_api_key is None:
            raise RuntimeError("OpenAI API key is not configured")
        timeout_seconds = max(
            settings.dependency_connect_timeout_seconds,
            settings.dependency_read_timeout_seconds,
        )
        _openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=timeout_seconds,
            max_retries=0,
        )
    return _openai_client


def _extract_message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
        return "\n".join(text_parts).strip()
    return ""


def _coerce_score(value: object) -> float | None:
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0.0, min(1.0, numeric))


async def _evaluate_with_llm_judge_async(
    *,
    model_name: str,
    question: str,
    expected_answer: str | None,
    generated_answer: str,
    retrieved_chunks: list[RetrievedChunk],
) -> EvaluationJudgeScores:
    context_lines: list[str] = []
    for index, chunk in enumerate(retrieved_chunks[:6], start=1):
        context_lines.append(
            f"[{index}] document_id={chunk.document_id} "
            f"chunk_id={chunk.chunk_id} filename={chunk.filename} page={chunk.page_number}\n"
            f"{chunk.text[:1200]}"
        )
    context_block = "\n\n".join(context_lines) if context_lines else "(no context)"
    expected_block = expected_answer.strip() if isinstance(expected_answer, str) and expected_answer.strip() else "(none)"
    prompt = (
        "Score the assistant answer for a RAG evaluation.\n"
        "Return strict JSON with keys: faithfulness_score, answer_relevance_score.\n"
        "Scores must be floats between 0 and 1.\n\n"
        f"Question:\n{question}\n\n"
        f"Expected answer (optional):\n{expected_block}\n\n"
        f"Assistant answer:\n{generated_answer}\n\n"
        f"Retrieved context:\n{context_block}\n"
    )
    response = await _get_openai_client().chat.completions.create(
        model=model_name,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an evaluation judge. Score only groundedness and relevance. "
                    "Do not return any keys except faithfulness_score and answer_relevance_score."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("Judge response did not include choices")
    raw_content = _extract_message_text(choices[0].message.content)
    payload = json.loads(raw_content)
    faithfulness_score = _coerce_score(payload.get("faithfulness_score"))
    answer_relevance_score = _coerce_score(payload.get("answer_relevance_score"))
    return EvaluationJudgeScores(
        faithfulness_score=faithfulness_score,
        answer_relevance_score=answer_relevance_score,
        provider="llm_judge",
    )


def _to_retrieved_chunk(candidate: RetrievedCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
    )


def _rerank_chunks(
    *,
    chunks: list[RetrievedChunk],
    enabled: bool,
    final_top_k: int,
) -> list[RetrievedChunk]:
    if final_top_k < 1 or not chunks:
        return []

    chunk_by_key = {str(chunk.chunk_id): chunk for chunk in chunks}
    rerank_inputs = [
        RerankCandidate(
            key=str(chunk.chunk_id),
            text=chunk.text,
            similarity_score=chunk.similarity_score,
        )
        for chunk in chunks
    ]
    rerank_results = _rerank_service.rerank(
        candidates=rerank_inputs,
        enabled=enabled,
        final_top_k=final_top_k,
    )

    selected_chunks: list[RetrievedChunk] = []
    for reranked in rerank_results:
        source_chunk = chunk_by_key.get(reranked.key)
        if source_chunk is None:
            continue
        selected_chunks.append(
            RetrievedChunk(
                document_id=source_chunk.document_id,
                chunk_id=source_chunk.chunk_id,
                filename=source_chunk.filename,
                page_number=source_chunk.page_number,
                text=source_chunk.text,
                similarity_score=source_chunk.similarity_score,
                rerank_score=reranked.rerank_score,
                rerank_rank=reranked.rerank_rank,
            )
        )
    return selected_chunks


def _build_prompt(*, question: str, chunks: list[RetrievedChunk]) -> str:
    return _prompt_service.build_prompt(
        question=question,
        not_found_answer=_NOT_FOUND_ANSWER,
        chunks=[
            PromptContextChunk(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
            )
            for chunk in chunks
        ],
    )


def _to_confidence_signals(*, chunks: list[RetrievedChunk], rerank_applied: bool) -> list[ConfidenceChunkSignal]:
    return [
        ConfidenceChunkSignal(
            similarity_score=chunk.similarity_score,
            rerank_score=chunk.rerank_score if rerank_applied else None,
        )
        for chunk in chunks
    ]


def _serialize_chunk(chunk: RetrievedChunk) -> dict[str, Any]:
    return {
        "document_id": str(chunk.document_id),
        "chunk_id": str(chunk.chunk_id),
        "filename": chunk.filename,
        "page_number": chunk.page_number,
        "similarity_score": round(float(chunk.similarity_score), 6),
        "rerank_score": round(float(chunk.rerank_score), 6) if chunk.rerank_score is not None else None,
        "rerank_rank": chunk.rerank_rank,
        "text_snippet": chunk.text[:400],
    }


def _parse_run_config(raw_config: dict[str, Any]) -> EvaluationRunConfig:
    raw_top_k = raw_config.get("top_k")
    if raw_top_k is None:
        top_k = settings.retrieval_final_top_k
    elif isinstance(raw_top_k, int) and 1 <= raw_top_k <= 200:
        top_k = raw_top_k
    else:
        raise PermanentTaskError("Invalid evaluation run config: top_k")

    raw_rerank = raw_config.get("rerank")
    if raw_rerank is None:
        rerank = True
    elif isinstance(raw_rerank, bool):
        rerank = raw_rerank
    else:
        raise PermanentTaskError("Invalid evaluation run config: rerank")

    raw_model_name = raw_config.get("model_name")
    if raw_model_name is None:
        model_name = settings.openai_llm_model
    elif isinstance(raw_model_name, str) and raw_model_name.strip():
        model_name = raw_model_name.strip()
    else:
        raise PermanentTaskError("Invalid evaluation run config: model_name")

    raw_selected_document_ids = raw_config.get("selected_document_ids", [])
    if not isinstance(raw_selected_document_ids, list):
        raise PermanentTaskError("Invalid evaluation run config: selected_document_ids")
    selected_document_ids: list[UUID] = []
    seen_document_ids: set[UUID] = set()
    for raw_document_id in raw_selected_document_ids:
        if not isinstance(raw_document_id, str) or not raw_document_id.strip():
            raise PermanentTaskError("Invalid evaluation run config: selected_document_ids")
        try:
            parsed_document_id = UUID(raw_document_id.strip())
        except ValueError as exc:
            raise PermanentTaskError("Invalid evaluation run config: selected_document_ids") from exc
        if parsed_document_id in seen_document_ids:
            continue
        seen_document_ids.add(parsed_document_id)
        selected_document_ids.append(parsed_document_id)

    raw_metric_options = raw_config.get("metric_options", {})
    if not isinstance(raw_metric_options, dict):
        raise PermanentTaskError("Invalid evaluation run config: metric_options")

    return EvaluationRunConfig(
        top_k=top_k,
        rerank=rerank,
        model_name=model_name,
        selected_document_ids=selected_document_ids,
        metric_options=_evaluation_metrics_service.parse_metric_options(
            dict(raw_metric_options)
        ),
    )


async def _evaluate_question_pipeline_async(
    *,
    question_text: str,
    expected_answer: str | None,
    expected_document_id: UUID | None,
    expected_page_number: int | None,
    organization_id: UUID,
    config: EvaluationRunConfig,
    llm_service: LLMService,
) -> EvaluationQuestionComputation:
    latencies_ms: dict[str, int] = {}
    total_started = perf_counter()
    embedding_model = _query_retrieval_service.embedding_model

    embed_started = perf_counter()
    query_vector, embedding_prompt_tokens = await _query_retrieval_service.embed_query(
        question=question_text,
        openai_client=_get_openai_client(),
    )
    latencies_ms["embed"] = int((perf_counter() - embed_started) * 1000)

    retrieval_top_k = max(
        config.top_k,
        _rerank_service.candidate_count if config.rerank else config.top_k,
    )
    retrieve_started = perf_counter()
    retrieved_candidates = _query_retrieval_service.retrieve_candidates(
        query_vector=query_vector,
        organization_id=organization_id,
        document_ids=config.selected_document_ids,
        initial_top_k=retrieval_top_k,
    )
    retrieved_chunks = [_to_retrieved_chunk(candidate) for candidate in retrieved_candidates]
    latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)

    rerank_started = perf_counter()
    selected_chunks = _rerank_chunks(
        chunks=retrieved_chunks,
        enabled=config.rerank,
        final_top_k=config.top_k,
    )
    latencies_ms["rerank"] = int((perf_counter() - rerank_started) * 1000)

    llm_prompt_tokens = 0
    llm_completion_tokens = 0
    llm_model: str | None = None
    llm_cost_usd: Decimal | None = None
    embedding_cost_usd = (
        (Decimal(embedding_prompt_tokens) / Decimal(1_000_000))
        * Decimal(str(settings.openai_embedding_cost_per_million_tokens_usd))
    )
    citation_validation_score = 1.0

    confidence_signals = _to_confidence_signals(chunks=selected_chunks, rerank_applied=config.rerank)
    confidence_result = _confidence_service.score(
        chunks=confidence_signals,
        citation_count=0,
        citation_validation_score=1.0,
        not_found_signal=False,
    )
    confidence_score = confidence_result.score
    confidence_category = confidence_result.category
    confidence_explanation = confidence_result.explanation
    not_found = len(selected_chunks) == 0 or confidence_score < settings.confidence_not_found_threshold
    if not_found:
        confidence_result = _confidence_service.score(
            chunks=confidence_signals,
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=True,
        )
        confidence_score = confidence_result.score
        confidence_category = confidence_result.category
        confidence_explanation = confidence_result.explanation

    prompt_started = perf_counter()
    prompt = _build_prompt(question=question_text, chunks=selected_chunks) if not not_found else ""
    latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

    answer = _NOT_FOUND_ANSWER
    citations: list[dict[str, Any]] = []
    judge_scores: EvaluationJudgeScores | None = None
    judge_error: str | None = None
    llm_latency_ms = 0
    if not not_found:
        try:
            llm_result = await llm_service.generate_answer(
                prompt=prompt,
                openai_client=_get_openai_client(),
            )
        except (TransientLLMServiceError, PermanentLLMServiceError) as exc:
            raise RuntimeError("llm_generation_failed") from exc

        llm_latency_ms = llm_result.latency_ms
        llm_model = llm_result.model_name
        llm_prompt_tokens = llm_result.prompt_tokens
        llm_completion_tokens = llm_result.completion_tokens
        llm_cost_usd = llm_result.approximate_cost_usd
        answer = llm_result.answer

        if llm_result.not_found or not answer.strip() or answer.strip() == _NOT_FOUND_ANSWER:
            answer = _NOT_FOUND_ANSWER
            not_found = True
        else:
            citation_result = _citation_service.build_citations(
                not_found=False,
                answer=answer,
                retrieved_chunks=[
                    CitationContextChunk(
                        document_id=chunk.document_id,
                        chunk_id=chunk.chunk_id,
                        filename=chunk.filename,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        similarity_score=chunk.similarity_score,
                        rerank_score=chunk.rerank_score,
                        rerank_rank=chunk.rerank_rank,
                    )
                    for chunk in selected_chunks
                ],
                model_citations=llm_result.citations,
            )
            citations = [citation.model_dump() for citation in citation_result.citations]
            citation_validation_score = citation_result.validation_score
            confidence_result = _confidence_service.score(
                chunks=confidence_signals,
                citation_count=len(citations),
                citation_validation_score=citation_validation_score,
                not_found_signal=False,
            )
            confidence_score = confidence_result.score
            confidence_category = confidence_result.category
            confidence_explanation = confidence_result.explanation

        if (
            not not_found
            and (config.metric_options.faithfulness_enabled or config.metric_options.answer_relevance_enabled)
        ):
            judge_model_name = config.metric_options.judge_model_name or config.model_name
            try:
                judge_scores = await _evaluate_with_llm_judge_async(
                    model_name=judge_model_name,
                    question=question_text,
                    expected_answer=expected_answer,
                    generated_answer=answer,
                    retrieved_chunks=selected_chunks,
                )
            except Exception as exc:
                judge_error = exc.__class__.__name__

        if not_found:
            confidence_result = _confidence_service.score(
                chunks=confidence_signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=True,
            )
            confidence_score = confidence_result.score
            confidence_category = confidence_result.category
            confidence_explanation = confidence_result.explanation
            citations = []
    latencies_ms["llm"] = llm_latency_ms

    total_latency_ms = int((perf_counter() - total_started) * 1000)
    latencies_ms["total"] = total_latency_ms
    citation_accuracy_score = citation_validation_score if citations else None
    total_cost_usd = (llm_cost_usd or Decimal("0")) + embedding_cost_usd
    question_metrics = _evaluation_metrics_service.score_question(
        expected_document_id=expected_document_id,
        expected_page_number=expected_page_number,
        expected_answer=expected_answer,
        generated_answer=answer,
        not_found=not_found,
        retrieved_chunks=[
            RetrievedMetricChunk(
                document_id=chunk.document_id,
                page_number=chunk.page_number,
            )
            for chunk in retrieved_chunks
        ],
        selected_chunk_count=len(selected_chunks),
        citation_count=len(citations),
        citation_accuracy_score=citation_accuracy_score,
        latency_ms=total_latency_ms,
        cost_usd=total_cost_usd,
        token_input_count=embedding_prompt_tokens + llm_prompt_tokens,
        token_output_count=llm_completion_tokens,
        options=config.metric_options,
        judge_scores=judge_scores,
        judge_error=judge_error,
    )
    retrieval_score = question_metrics.retrieval_hit_rate
    if retrieval_score is None:
        retrieval_score = retrieved_chunks[0].similarity_score if retrieved_chunks else None

    details: dict[str, Any] = {
        "status": "completed",
        "question": question_text,
        "expected_answer": expected_answer,
        "expected_document_id": str(expected_document_id) if expected_document_id is not None else None,
        "expected_page_number": expected_page_number,
        "not_found": not_found,
        "confidence_score": confidence_score,
        "confidence_category": confidence_category,
        "confidence_explanation": asdict(confidence_explanation),
        "citation_validation_score": citation_validation_score,
        "latencies_ms": latencies_ms,
        "retrieval_count": len(retrieved_chunks),
        "selected_count": len(selected_chunks),
        "rerank_applied": config.rerank,
        "embedding_model": embedding_model,
        "llm_model": llm_model,
        "token_input_count": embedding_prompt_tokens + llm_prompt_tokens,
        "token_output_count": llm_completion_tokens,
        "cost_usd": float(total_cost_usd),
        "embedding_cost_usd": float(embedding_cost_usd),
        "llm_cost_usd": float(llm_cost_usd) if llm_cost_usd is not None else 0.0,
        "citations": citations,
        "retrieved_chunks": [_serialize_chunk(chunk) for chunk in retrieved_chunks],
        "selected_chunks": [_serialize_chunk(chunk) for chunk in selected_chunks],
        "metric_options": config.metric_options.as_dict(),
        "metrics": question_metrics.as_dict(),
    }
    return EvaluationQuestionComputation(
        generated_answer=answer,
        retrieval_score=retrieval_score,
        faithfulness_score=question_metrics.faithfulness_score,
        citation_accuracy_score=question_metrics.citation_accuracy_score,
        answer_relevance_score=question_metrics.answer_relevance_score,
        metrics=question_metrics,
        latency_ms=total_latency_ms,
        details=details,
    )


async def _run_evaluation_async(
    evaluation_run_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    try:
        parsed_run_id = _parse_uuid(evaluation_run_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid evaluation_run_id: {evaluation_run_id}") from exc

    async with SessionLocal() as session:
        evaluation_run = await _evaluation_repository.get_evaluation_run(
            session,
            evaluation_run_id=parsed_run_id,
        )
        if evaluation_run is None:
            raise PermanentTaskError(f"Evaluation run not found: {evaluation_run_id}")

        evaluation_set = await _evaluation_repository.get_evaluation_set_by_id(
            session,
            evaluation_set_id=evaluation_run.evaluation_set_id,
        )
        if evaluation_set is None:
            raise PermanentTaskError(
                f"Evaluation set not found for run: {evaluation_run.evaluation_set_id}"
            )

        questions = await _evaluation_repository.list_all_evaluation_questions(
            session,
            evaluation_set_id=evaluation_set.id,
        )
        run_config = _parse_run_config(evaluation_run.config if isinstance(evaluation_run.config, dict) else {})
        llm_service = LLMService(model_name=run_config.model_name)

        # Idempotent retry behavior: replace previous results for this run.
        try:
            _ = await _evaluation_repository.delete_evaluation_results_for_run(
                session,
                evaluation_run_id=parsed_run_id,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to clear stale evaluation results for run: {evaluation_run_id}"
            ) from exc

        question_success_count = 0
        question_failure_count = 0
        successful_metrics: list[EvaluationQuestionMetrics] = []
        for question in questions:
            question_started = perf_counter()
            try:
                computed = await _evaluate_question_pipeline_async(
                    question_text=question.question,
                    expected_answer=question.expected_answer,
                    expected_document_id=question.expected_document_id,
                    expected_page_number=question.expected_page_number,
                    organization_id=evaluation_set.organization_id,
                    config=run_config,
                    llm_service=llm_service,
                )
            except Exception as exc:
                question_failure_count += 1
                failed_metrics = _evaluation_metrics_service.score_question(
                    expected_document_id=question.expected_document_id,
                    expected_page_number=question.expected_page_number,
                    expected_answer=question.expected_answer,
                    generated_answer="",
                    not_found=True,
                    retrieved_chunks=[],
                    selected_chunk_count=0,
                    citation_count=0,
                    citation_accuracy_score=None,
                    latency_ms=int((perf_counter() - question_started) * 1000),
                    cost_usd=0.0,
                    token_input_count=0,
                    token_output_count=0,
                    options=run_config.metric_options,
                    judge_scores=None,
                    judge_error=exc.__class__.__name__,
                )
                computed = EvaluationQuestionComputation(
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
                log_evaluation_event(
                    event="evaluation.question.failed",
                    organization_id=organization_id or str(evaluation_set.organization_id),
                    user_id=user_id,
                    job_id=evaluation_run_id,
                    request_id=request_id,
                    question_id=str(question.id),
                    error=exc.__class__.__name__,
                )
            else:
                question_success_count += 1
                successful_metrics.append(computed.metrics)
                log_evaluation_event(
                    event="evaluation.question.completed",
                    organization_id=organization_id or str(evaluation_set.organization_id),
                    user_id=user_id,
                    job_id=evaluation_run_id,
                    request_id=request_id,
                    question_id=str(question.id),
                    not_found=computed.details.get("not_found"),
                    confidence_score=computed.answer_relevance_score,
                )

            try:
                await _evaluation_repository.create_evaluation_result(
                    session,
                    evaluation_run_id=parsed_run_id,
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

        total_questions = len(questions)
        metrics_summary = _evaluation_metrics_service.summarize_run(
            metrics=successful_metrics,
            total_questions=total_questions,
            success_count=question_success_count,
            failure_count=question_failure_count,
        )
        try:
            updated_run = await _evaluation_repository.update_evaluation_run_config(
                session,
                evaluation_run_id=parsed_run_id,
                config_patch={
                    "metrics_summary": metrics_summary,
                    "metric_options_effective": run_config.metric_options.as_dict(),
                },
            )
            if updated_run is None:
                raise RuntimeError("evaluation run not found while updating summary")
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to persist evaluation summary for run: {evaluation_run_id}"
            ) from exc

        log_evaluation_event(
            event="evaluation.run.metrics_computed",
            organization_id=organization_id or str(evaluation_set.organization_id),
            user_id=user_id,
            job_id=evaluation_run_id,
            request_id=request_id,
            metrics_summary=metrics_summary,
        )
        return {
            "evaluation_run_id": evaluation_run_id,
            "question_total_count": total_questions,
            "question_success_count": question_success_count,
            "question_failure_count": question_failure_count,
            "all_questions_failed": total_questions > 0 and question_success_count == 0,
            "metrics_summary": metrics_summary,
        }


class EvaluationTask(RudixTask):
    abstract = True

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        evaluation_run_id = kwargs.get("evaluation_run_id")
        if evaluation_run_id is None and args:
            evaluation_run_id = args[0]
        if not isinstance(evaluation_run_id, str):
            return
        try:
            set_evaluation_status(
                evaluation_run_id,
                status=EvaluationRunStatus.failed,
                mark_completed=True,
            )
            log_evaluation_event(
                event="evaluation.run.failed",
                job_id=evaluation_run_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=EvaluationRunStatus.failed.value,
                error=str(exc),
            )
            _record_worker_audit(
                action="evaluation.run.failed",
                resource_type="evaluation_run",
                resource_id=evaluation_run_id,
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                request_id=kwargs.get("request_id"),
                metadata={
                    "status": EvaluationRunStatus.failed.value,
                    "task_name": self.name,
                    "error_type": exc.__class__.__name__,
                },
            )
        except Exception:
            return


@celery_app.task(name="evaluations.run", bind=True, base=EvaluationTask)
def run_evaluation(
    self: EvaluationTask,
    evaluation_run_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run evaluation questions through the query pipeline and persist per-question outcomes."""
    try:
        status = get_evaluation_status(evaluation_run_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid evaluation_run_id: {evaluation_run_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Evaluation run not found: {evaluation_run_id}")

    if not force and status == EvaluationRunStatus.completed.value:
        log_evaluation_event(
            event="evaluation.run.skipped",
            job_id=evaluation_run_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code=status,
        )
        return {"evaluation_run_id": evaluation_run_id, "status": "skipped"}

    running_updated = set_evaluation_status(
        evaluation_run_id,
        status=EvaluationRunStatus.running,
        mark_started=True,
    )
    if not running_updated:
        raise TransientTaskError(f"Unable to move evaluation run to running state: {evaluation_run_id}")

    log_evaluation_event(
        event="evaluation.run.started",
        job_id=evaluation_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=EvaluationRunStatus.running.value,
    )

    summary = _run(
        _run_evaluation_async(
            evaluation_run_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )
    final_status = (
        EvaluationRunStatus.failed
        if summary["all_questions_failed"]
        else EvaluationRunStatus.completed
    )

    completed_updated = set_evaluation_status(
        evaluation_run_id,
        status=final_status,
        mark_completed=True,
    )
    if not completed_updated:
        raise TransientTaskError(f"Unable to move evaluation run to final state: {evaluation_run_id}")

    log_evaluation_event(
        event="evaluation.run.completed",
        job_id=evaluation_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=final_status.value,
        question_total_count=summary["question_total_count"],
        question_success_count=summary["question_success_count"],
        question_failure_count=summary["question_failure_count"],
    )
    _record_worker_audit(
        action="evaluation.run.completed",
        resource_type="evaluation_run",
        resource_id=evaluation_run_id,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        metadata={
            "status": final_status.value,
            "question_total_count": summary["question_total_count"],
            "question_success_count": summary["question_success_count"],
            "question_failure_count": summary["question_failure_count"],
        },
    )
    return {
        "evaluation_run_id": evaluation_run_id,
        "status": final_status.value,
        "question_total_count": summary["question_total_count"],
        "question_success_count": summary["question_success_count"],
        "question_failure_count": summary["question_failure_count"],
        "metrics_summary": summary.get("metrics_summary"),
    }
