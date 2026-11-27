"""One evaluation question through the query pipeline: retrieve, rerank, answer, score.

The pipeline opens no database session: retrieval, rerank, the LLM and the judge are
provider calls, so concurrent questions (``target.py``) never share a session.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.domains.ai.profile.schemas import ResolvedTaskProfile
from app.domains.chat.services.citation_service import CitationContextChunk
from app.domains.chat.services.confidence_service import ConfidenceChunkSignal
from app.domains.chat.services.llm_service import (
    LLMService,
    PermanentLLMServiceError,
    TransientLLMServiceError,
)
from app.domains.chat.services.prompt_service import PromptContextChunk
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate
from app.domains.chat.services.rerank_service import RerankCandidate, RerankResult
from app.domains.evaluations.services.evaluation_metrics_service import (
    EvaluationJudgeScores,
    EvaluationQuestionMetrics,
    RetrievedMetricChunk,
)
from app.workers.evaluation import facade
from app.workers.evaluation.config import EvaluationRunConfig

_NOT_FOUND_ANSWER = "I could not find this information in the uploaded documents."


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    original_rank: int | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None
    final_rank: int | None = None


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


def _to_retrieved_chunk(candidate: RetrievedCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
    )


def _with_original_ranks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    ranked_chunks: list[RetrievedChunk] = []
    for index, chunk in enumerate(chunks, start=1):
        ranked_chunks.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=index,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
            )
        )
    return ranked_chunks


async def _rerank_chunks(
    *,
    query: str,
    chunks: list[RetrievedChunk],
    enabled: bool,
    final_top_k: int,
) -> tuple[list[RetrievedChunk], RerankResult]:
    rerank_service = facade()._rerank_service
    if final_top_k < 1 or not chunks:
        empty_result = await rerank_service.rerank(
            query=query,
            candidates=[],
            enabled=enabled,
            final_top_k=final_top_k,
        )
        return [], empty_result

    chunk_by_key = {str(chunk.chunk_id): chunk for chunk in chunks}
    rerank_inputs = [
        RerankCandidate(
            key=str(chunk.chunk_id),
            text=chunk.text,
            similarity_score=chunk.similarity_score,
            original_rank=chunk.original_rank,
        )
        for chunk in chunks
    ]
    rerank_result = await rerank_service.rerank(
        query=query,
        candidates=rerank_inputs,
        enabled=enabled,
        final_top_k=final_top_k,
    )

    selected_chunks: list[RetrievedChunk] = []
    for reranked in rerank_result.candidates:
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
                original_rank=reranked.original_rank,
                rerank_score=reranked.rerank_score,
                rerank_rank=reranked.rerank_rank,
                final_rank=reranked.final_rank,
            )
        )
    return selected_chunks, rerank_result


def _build_prompt(
    *,
    question: str,
    chunks: list[RetrievedChunk],
    template: str | None = None,
) -> str:
    return facade()._prompt_service.build_prompt(
        question=question,
        not_found_answer=_NOT_FOUND_ANSWER,
        template=template,
        chunks=[
            PromptContextChunk(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=chunk.original_rank,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
            )
            for chunk in chunks
        ],
    )


def _to_confidence_signals(
    *, chunks: list[RetrievedChunk], rerank_applied: bool
) -> list[ConfidenceChunkSignal]:
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
        "original_rank": chunk.original_rank,
        "rerank_score": round(float(chunk.rerank_score), 6)
        if chunk.rerank_score is not None
        else None,
        "rerank_rank": chunk.rerank_rank,
        "final_rank": chunk.final_rank,
        "text_snippet": chunk.text[:400],
    }


def _score_confidence(
    signals: list[ConfidenceChunkSignal],
    *,
    citation_count: int = 0,
    citation_validation_score: float = 1.0,
    not_found: bool,
) -> Any:
    return facade()._confidence_service.score(
        chunks=signals,
        citation_count=citation_count,
        citation_validation_score=citation_validation_score,
        not_found_signal=not_found,
    )


async def _retrieve(
    service: Any, *, offload_blocking: bool, **kwargs: Any
) -> list[RetrievedCandidate]:
    """Synchronous Qdrant search; in a worker thread when questions run concurrently."""
    if offload_blocking:
        result: list[RetrievedCandidate] = await asyncio.to_thread(
            service.retrieve_candidates, **kwargs
        )
        return result
    candidates: list[RetrievedCandidate] = service.retrieve_candidates(**kwargs)
    return candidates


async def _evaluate_question_pipeline_async(
    *,
    question_text: str,
    expected_answer: str | None,
    expected_document_id: UUID | None,
    expected_page_number: int | None,
    organization_id: UUID,
    config: EvaluationRunConfig,
    llm_service: LLMService,
    index_version: str | None = None,
    prompt_template_content: str | None = None,
    prompt_template_metadata: dict[str, Any] | None = None,
    resolved_profile: ResolvedTaskProfile | None = None,
    retrieval_service: Any | None = None,
    offload_blocking: bool = False,
) -> EvaluationQuestionComputation:
    f = facade()
    service = retrieval_service if retrieval_service is not None else f._query_retrieval_service
    latencies_ms: dict[str, int] = {}
    total_started = perf_counter()
    embedding_model = service.embedding_model

    embed_started = perf_counter()
    query_vector, embedding_prompt_tokens = await service.embed_query(question=question_text)
    latencies_ms["embed"] = int((perf_counter() - embed_started) * 1000)

    retrieval_top_k = max(
        config.top_k,
        f._rerank_service.candidate_count if config.rerank else config.top_k,
    )
    retrieve_started = perf_counter()
    retrieved_candidates = await _retrieve(
        service,
        offload_blocking=offload_blocking,
        query_vector=query_vector,
        organization_id=organization_id,
        document_ids=config.selected_document_ids,
        initial_top_k=retrieval_top_k,
        index_version=index_version,
    )
    retrieved_chunks = _with_original_ranks(
        [_to_retrieved_chunk(candidate) for candidate in retrieved_candidates]
    )
    latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)

    rerank_started = perf_counter()
    selected_chunks, _rerank_result = await _rerank_chunks(
        query=question_text,
        chunks=retrieved_chunks,
        enabled=config.rerank,
        final_top_k=config.top_k,
    )
    latencies_ms["rerank"] = int((perf_counter() - rerank_started) * 1000)

    llm_prompt_tokens = 0
    llm_completion_tokens = 0
    llm_model: str | None = None
    llm_cost_usd: Decimal | None = None
    embedding_cost_usd = (Decimal(embedding_prompt_tokens) / Decimal(1_000_000)) * Decimal(
        str(settings.openai_embedding_cost_per_million_tokens_usd)
    )
    citation_validation_score = 1.0

    signals = _to_confidence_signals(chunks=selected_chunks, rerank_applied=config.rerank)
    confidence_result = _score_confidence(signals, not_found=False)
    not_found = (
        len(selected_chunks) == 0
        or confidence_result.score < settings.confidence_not_found_threshold
    )
    if not_found:
        confidence_result = _score_confidence(signals, not_found=True)

    prompt_started = perf_counter()
    prompt = (
        _build_prompt(
            question=question_text,
            chunks=selected_chunks,
            template=prompt_template_content,
        )
        if not not_found
        else ""
    )
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
                resolved_profile=resolved_profile,
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
            citation_result = f._citation_service.build_citations(
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
            confidence_result = _score_confidence(
                signals,
                citation_count=len(citations),
                citation_validation_score=citation_validation_score,
                not_found=False,
            )

        if not not_found and (
            config.metric_options.faithfulness_enabled
            or config.metric_options.answer_relevance_enabled
        ):
            judge_model_name = config.metric_options.judge_model_name or config.model_name
            try:
                judge_scores = await f._evaluate_with_llm_judge_async(
                    model_name=judge_model_name,
                    question=question_text,
                    expected_answer=expected_answer,
                    generated_answer=answer,
                    retrieved_chunks=selected_chunks,
                    resolved_profile=resolved_profile,
                )
            except Exception as exc:
                judge_error = exc.__class__.__name__

        if not_found:
            confidence_result = _score_confidence(signals, not_found=True)
            citations = []
    latencies_ms["llm"] = llm_latency_ms

    total_latency_ms = int((perf_counter() - total_started) * 1000)
    latencies_ms["total"] = total_latency_ms
    citation_accuracy_score = citation_validation_score if citations else None
    total_cost_usd = (llm_cost_usd or Decimal("0")) + embedding_cost_usd
    question_metrics = f._evaluation_metrics_service.score_question(
        expected_document_id=expected_document_id,
        expected_page_number=expected_page_number,
        expected_answer=expected_answer,
        generated_answer=answer,
        not_found=not_found,
        retrieved_chunks=[
            RetrievedMetricChunk(document_id=chunk.document_id, page_number=chunk.page_number)
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

    provider_key = (
        resolved_profile.provider_type
        if resolved_profile is not None
        else settings.llm_default_provider
    )
    details: dict[str, Any] = {
        "status": "completed",
        "question": question_text,
        "expected_answer": expected_answer,
        "expected_document_id": str(expected_document_id)
        if expected_document_id is not None
        else None,
        "expected_page_number": expected_page_number,
        "not_found": not_found,
        "confidence_score": confidence_result.score,
        "confidence_category": confidence_result.category,
        "confidence_explanation": asdict(confidence_result.explanation),
        "citation_validation_score": citation_validation_score,
        "latencies_ms": latencies_ms,
        "retrieval_count": len(retrieved_chunks),
        "selected_count": len(selected_chunks),
        "rerank_applied": config.rerank,
        "embedding_model": embedding_model,
        "llm_model": llm_model,
        "provider_key": provider_key,
        "provider_type": resolved_profile.provider_type if resolved_profile is not None else None,
        "base_model": resolved_profile.base_model
        if resolved_profile is not None
        else config.model_name,
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
    if prompt_template_metadata is not None:
        details["prompt_template"] = dict(prompt_template_metadata)
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
