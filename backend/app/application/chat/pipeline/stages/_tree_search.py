"""Tree-search reasoning over several answer candidates (R05-01).

Runs for high-risk questions with enough context. Each candidate's citations are validated
against the retrieved chunks before it is scored; a rejected selection becomes not-found.
"""

from decimal import Decimal

from app.application.chat.pipeline.context import NOT_FOUND_ANSWER, ChatContext
from app.application.chat.pipeline.controls import _resolve_tree_search_reasoning_enabled
from app.application.chat.pipeline.stages._llm import apply_llm_result
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.chat.schemas.chat import ChatCitationResponse
from app.domains.chat.services.citation_enrichment import (
    _build_conflict_context,
    _with_conflict_status,
    _with_freshness,
    _with_ocr_quality,
)
from app.domains.chat.services.citation_service import CitationBuildResult, CitationContextChunk
from app.domains.chat.services.confidence_calibration import (
    _compute_conflict_multiplier,
    _compute_freshness_multiplier,
    _compute_ocr_quality_multiplier,
)
from app.domains.chat.services.llm_service import LLMAnswerResult
from app.domains.chat.services.tree_search_service import TreeSearchCandidateScore

Evaluation = tuple[
    TreeSearchCandidateScore,
    CitationBuildResult,
    list[ChatCitationResponse],
    LLMAnswerResult,
]


def empty_citation_result() -> CitationBuildResult:
    return CitationBuildResult(
        citations=[],
        model_citation_count=0,
        accepted_model_citation_count=0,
        used_fallback=False,
        validation_score=1.0,
        invalid_chunk_id_count=0,
        metadata_mismatch_count=0,
        snippet_mismatch_count=0,
    )


def context_chunks(ctx: ChatContext) -> list[CitationContextChunk]:
    return [
        CitationContextChunk(
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            filename=chunk.filename,
            page_number=chunk.page_number,
            text=chunk.text,
            similarity_score=chunk.similarity_score,
            original_rank=chunk.original_rank,
            rerank_score=chunk.rerank_score,
            rerank_rank=chunk.rerank_rank,
            final_rank=chunk.final_rank,
        )
        for chunk in ctx.retrieval.selected_chunks
    ]


def log_citation_validation(ctx: ChatContext, citation_result: CitationBuildResult) -> None:
    principal = ctx.request.principal
    log_query_event(
        event="query.citations.validated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=ctx.job_id,
        validation_score=citation_result.validation_score,
        model_citation_count=citation_result.model_citation_count,
        accepted_model_citation_count=citation_result.accepted_model_citation_count,
        used_fallback=citation_result.used_fallback,
        invalid_chunk_id_count=citation_result.invalid_chunk_id_count,
        metadata_mismatch_count=citation_result.metadata_mismatch_count,
        snippet_mismatch_count=citation_result.snippet_mismatch_count,
    )
    if ctx.verification.citation_validation_failed:
        log_query_event(
            event="query.citations.validation_failed",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=ctx.job_id,
            invalid_chunk_id_count=citation_result.invalid_chunk_id_count,
        )


async def run_tree_search(ctx: ChatContext) -> None:
    """Try tree search; on an accepted (or rejected) selection set ``citation_result``."""
    req = ctx.request
    ret = ctx.retrieval
    gen = ctx.generation
    planner_result = ctx.config.planner_result
    async with ctx.sessions.short() as db_session:
        enabled = await _resolve_tree_search_reasoning_enabled(
            db_session, organization_id=req.organization_id
        )
    applicable = (
        enabled
        and planner_result is not None
        and planner_result.high_risk
        and len(ret.selected_chunks) >= settings.tree_search_min_context_chunks
    )
    if not applicable:
        return
    tree_chunks = context_chunks(ctx)
    tree = ctx.deps.tree_search_service
    result = await tree.generate_candidates(
        question=req.payload.question,
        context_chunks=tree_chunks,
        not_found_answer=NOT_FOUND_ANSWER,
        conflict_context=_build_conflict_context(ret.conflict_detection_result),
        answer_language=ctx.config.answer_language_used,
        resolved_profile=ctx.config.chat_profile,
        max_candidates=settings.tree_search_max_candidates,
        timeout_seconds=settings.tree_search_timeout_seconds,
        max_total_tokens=settings.tree_search_max_total_tokens,
        max_total_cost_usd=Decimal(str(settings.tree_search_max_total_cost_usd)),
    )
    ctx.latencies_ms["tree_search"] = result.latency_ms
    if result.candidate_count <= 0:
        return
    scores: list[TreeSearchCandidateScore] = []
    evaluations: list[Evaluation] = []
    for candidate in result.candidates:
        candidate_result = ctx.deps.citation_service.build_citations(
            not_found=False,
            answer=candidate.llm_result.answer,
            retrieved_chunks=tree_chunks,
            model_citations=candidate.llm_result.citations,
        )
        candidate_citations: list[ChatCitationResponse] = [
            _with_conflict_status(
                _with_ocr_quality(
                    _with_freshness(citation, ret.freshness_trust_map, ret.freshness_stale_ids),
                    {str(k): v for k, v in ret.ocr_quality_map.items()},
                ),
                ret.conflict_detection_result,
            )
            for citation in candidate_result.citations
        ]
        score = tree.score_candidate(
            candidate=candidate,
            citations=candidate_citations,
            confidence_signals=ctx.verification.confidence_signals,
            citation_validation_score=candidate_result.validation_score,
            freshness_multiplier=_compute_freshness_multiplier(
                ret.freshness_stale_count, len(candidate_citations)
            ),
            ocr_quality_multiplier=_compute_ocr_quality_multiplier(candidate_citations),
            conflict_multiplier=_compute_conflict_multiplier(ret.conflict_detection_result),
            table_quality_multiplier=1.0,
            extraction_quality_multiplier=1.0,
            graph_context_used=ret.graph_context_result.graph_context_used,
        )
        scores.append(score)
        evaluations.append((score, candidate_result, candidate_citations, candidate.llm_result))

    selection = tree.select_candidate(
        scores, min_selected_score=settings.tree_search_min_selected_score
    )
    if selection.selected_candidate is None:
        return
    selected_score = selection.selected_candidate
    selected = next(
        (ev for ev in evaluations if ev[0].strategy == selected_score.strategy),
        None,
    )
    if selected is None and evaluations:
        selected = evaluations[0]
    if selected is not None and selection.accepted:
        _, citation_result, citations, llm_result = selected
        gen.llm_result = llm_result
        apply_llm_result(ctx, llm_result, stage="generate")
        gen.answer = llm_result.answer
        gen.citation_result = citation_result
        gen.citations = citations
        ctx.verification.citation_validation_failed = citation_result.invalid_chunk_id_count > 0
        log_citation_validation(ctx, citation_result)
    elif selected is not None:
        best = selected[3]
        llm_result = LLMAnswerResult(
            answer="",
            not_found=True,
            citations=[],
            model_name=best.model_name,
            prompt_tokens=best.prompt_tokens,
            completion_tokens=best.completion_tokens,
            total_tokens=best.total_tokens,
            approximate_cost_usd=best.approximate_cost_usd,
            latency_ms=best.latency_ms,
            retry_count=best.retry_count,
            used_fallback_parser=best.used_fallback_parser,
            provider_key=best.provider_key,
            fallback_used=best.fallback_used,
            fallback_from=best.fallback_from,
            fallback_to=best.fallback_to,
            fallback_reason=best.fallback_reason,
        )
        gen.llm_result = llm_result
        apply_llm_result(ctx, llm_result, stage="generate")
        gen.answer = NOT_FOUND_ANSWER
        gen.not_found = True
        gen.citations = []
        gen.citation_result = empty_citation_result()
