"""Record builders for the answer trust metadata (R05-01)."""

from uuid import UUID

from app.domains.chat.schemas.chat import (
    ChatCitationResponse,
    ChatQueryRequest,
)
from app.domains.chat.schemas.trust_metadata import (
    ChatToolCallRecord,
    ClaimSupportRecord,
    CriticWarningRecord,
    PlannerCriticRecord,
    RetrievalBranchRecord,
    RetrievalMethodRecord,
    ToolOrchestrationRecord,
)
from app.domains.chat.services.answer_critic_service import CriticResult
from app.domains.chat.services.answer_planner_service import (
    PlannerResult,
)
from app.domains.chat.services.answer_refiner_service import RefinerResult
from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievalResult,
)
from app.domains.chat.services.grounded_answer_verifier import (
    GroundedVerifierResult,
    VerifierCitation,
)
from app.domains.chat.services.parallel_retrieval_optimizer import (
    ParallelRetrievalResult,
)
from app.domains.chat.services.query_intent_service import (
    _build_retrieval_filters,
    _build_retrieval_profile_scope,
    _build_search_mode,
)
from app.domains.chat.services.retrieval_strategy_router import (
    RetrievalRouteResult,
)
from app.domains.chat.services.retrieved_chunk import RetrievedChunk
from app.domains.chat.services.source_scope_service import (
    ResolvedSourceScope,
)
from app.domains.chat.services.tool_orchestrator import (
    ToolOrchestrationResult,
)


def _build_retrieval_method_record(
    route_result: "RetrievalRouteResult | None",
) -> RetrievalMethodRecord:
    """Build a RetrievalMethodRecord from a route result (F341).

    Returns an empty default record when routing is disabled or unavailable.
    """
    if route_result is None:
        return RetrievalMethodRecord()
    return RetrievalMethodRecord(
        method=route_result.method,
        method_label=route_result.method_label,
        override_applied=route_result.override_applied,
        override_source=route_result.override_source,  # type: ignore[arg-type]
        routing_latency_ms=route_result.routing_latency_ms,
    )


def _build_parallel_branch_records(
    parallel_result: ParallelRetrievalResult | None,
) -> list[RetrievalBranchRecord]:
    if parallel_result is None:
        return []
    return [
        RetrievalBranchRecord(
            branch_name=record.branch_name,
            latency_ms=record.latency_ms,
            succeeded=record.succeeded,
            retries=record.retries,
            candidate_count=record.candidate_count,
            error_code=record.error_code,
            skipped=record.skipped,
        )
        for record in parallel_result.branch_records
    ]


def _build_tool_orchestration_record(
    orchestration_result: "ToolOrchestrationResult | None",
) -> ToolOrchestrationRecord:
    """Build a ToolOrchestrationRecord for trust metadata from pipeline state (F342).

    Returns an empty default record when orchestration is disabled or unavailable.
    """
    if orchestration_result is None or not orchestration_result.enabled:
        return ToolOrchestrationRecord()
    return ToolOrchestrationRecord(
        enabled=True,
        tool_count=orchestration_result.tool_count,
        authorized_count=orchestration_result.authorized_count,
        executed_count=orchestration_result.executed_count,
        succeeded_count=orchestration_result.succeeded_count,
        fallback_count=orchestration_result.fallback_count,
        denied_count=orchestration_result.denied_count,
        orchestration_latency_ms=orchestration_result.orchestration_latency_ms,
        tool_calls=[
            ChatToolCallRecord(
                tool_name=t.tool_name,
                tool_purpose=t.tool_purpose,
                authorized=t.authorized,
                executed=t.executed,
                succeeded=t.succeeded,
                fallback_used=t.fallback_used,
                latency_ms=t.latency_ms,
                denial_reason=t.denial_reason,
                error_code=t.error_code,
            )
            for t in orchestration_result.tool_calls
        ],
    )


def _build_planner_critic_record(
    *,
    planner_result: "PlannerResult | None",
    critic_result: "CriticResult | None",
    refiner_result: "RefinerResult | None",
) -> PlannerCriticRecord:
    """Build the PlannerCriticRecord for trust metadata from pipeline state."""
    if planner_result is None:
        return PlannerCriticRecord()

    _severity_label = {1: "low", 2: "medium", 3: "high"}
    critic_warnings: list[CriticWarningRecord] = []
    critic_severity = "none"
    if critic_result is not None:
        critic_severity = critic_result.severity
        for w in critic_result.warnings:
            critic_warnings.append(
                CriticWarningRecord(
                    code=w.code,
                    detail=w.detail,
                    severity=_severity_label.get(w.severity_level, "low"),  # type: ignore[arg-type]
                )
            )

    refiner_applied = False
    draft_changed = False
    unsupported_removed = 0
    refiner_latency_ms = 0
    if refiner_result is not None:
        refiner_applied = refiner_result.applied
        draft_changed = refiner_result.draft_changed
        unsupported_removed = refiner_result.unsupported_claims_removed
        refiner_latency_ms = refiner_result.latency_ms

    return PlannerCriticRecord(
        strategy=planner_result.strategy,
        high_risk=planner_result.high_risk,
        critic_warnings=critic_warnings,
        critic_severity=critic_severity,  # type: ignore[arg-type]
        refiner_applied=refiner_applied,
        draft_changed=draft_changed,
        unsupported_claims_removed=unsupported_removed,
        planner_latency_ms=planner_result.latency_ms,
        critic_latency_ms=critic_result.latency_ms if critic_result is not None else 0,
        refiner_latency_ms=refiner_latency_ms,
    )


def _build_verifier_citations(citations: list[ChatCitationResponse]) -> list[VerifierCitation]:
    verifier_citations: list[VerifierCitation] = []
    for citation in citations:
        if not citation.document_id or not citation.chunk_id:
            continue
        verifier_citations.append(
            VerifierCitation(
                document_id=citation.document_id,
                chunk_id=citation.chunk_id,
                filename=citation.filename or "",
                page_number=citation.page_number,
                text_snippet=(citation.text_snippet or "")[:400],
                score=citation.score or 0.0,
                similarity_score=citation.similarity_score or 0.0,
                rerank_score=citation.rerank_score,
                source_trust_status=citation.source_trust_status,
                doc_ocr_quality_status=citation.doc_ocr_quality_status,
                doc_ocr_low_confidence_warning=citation.doc_ocr_low_confidence_warning,
                doc_stale_warning=citation.doc_stale_warning,
                doc_expired_warning=citation.doc_expired_warning,
                doc_is_excluded_status=citation.doc_is_excluded_status,
            )
        )
    return verifier_citations


def _build_claim_support_records(
    *,
    grounded_verifier_result: GroundedVerifierResult | None,
) -> list[ClaimSupportRecord]:
    if grounded_verifier_result is None:
        return []
    records: list[ClaimSupportRecord] = []
    for claim_index, claim in enumerate(grounded_verifier_result.claims, start=1):
        records.append(
            ClaimSupportRecord(
                claim_index=claim_index,
                claim_text=claim.claim_text,
                support_status=claim.support_status,
                support_score=claim.support_score,
                evidence_match_score=claim.evidence_match_score,
                source_quality_score=claim.source_quality_score,
                rerank_score=claim.rerank_score,
                chunk_coverage_score=claim.chunk_coverage_score,
                citation_indices=list(claim.citation_indices),
            )
        )
    return records


def _build_rerank_score_range(chunks: list[RetrievedChunk]) -> tuple[float | None, float | None]:
    scores = [
        score
        for score in (chunk.rerank_score for chunk in chunks)
        if isinstance(score, (int, float))
    ]
    if not scores:
        return None, None
    return min(scores), max(scores)


def _build_retrieval_diagnostics_payload(
    *,
    request_id: str | None,
    rag_profile: object | None,
    rag_profile_source: str,
    payload: ChatQueryRequest,
    source_scope_result: ResolvedSourceScope,
    retrieved_chunks: list[RetrievedChunk],
    selected_chunks: list[RetrievedChunk],
    rerank_applied: bool,
    rerank_diagnostics: object | None,
    parallel_result: ParallelRetrievalResult | None,
    hybrid_retrieval_enabled: bool,
    hybrid_vector_hit_count: int,
    hybrid_keyword_hit_count: int,
    query_rewrite_result: object | None,
    graph_context_result: GraphRetrievalResult,
    document_ids: list[UUID] | None,
    final_top_k: int,
) -> dict[str, object]:
    profile_name = getattr(rag_profile, "name", None) if rag_profile is not None else None
    search_mode = _build_search_mode(
        hybrid_retrieval_enabled=hybrid_retrieval_enabled,
        graph_context_result=graph_context_result,
    )
    retrieval_profile_scope = _build_retrieval_profile_scope(
        payload=payload,
        source_scope_result=source_scope_result,
        graph_context_result=graph_context_result,
        document_ids=document_ids,
    )
    retrieval_filters = _build_retrieval_filters(
        payload=payload,
        source_scope_result=source_scope_result,
        document_ids=document_ids,
        graph_context_result=graph_context_result,
    )
    rerank_score_min, rerank_score_max = _build_rerank_score_range(retrieved_chunks)
    rerank_fallback_used = bool(getattr(rerank_diagnostics, "fallback_used", False))
    rerank_fallback_reason = getattr(rerank_diagnostics, "fallback_reason", None)
    parallel_branches = _build_parallel_branch_records(parallel_result)
    return {
        "retrieval_candidate_count": len(retrieved_chunks),
        "retrieval_count": len(retrieved_chunks),
        "selected_count": len(selected_chunks),
        "top_k": final_top_k,
        "search_mode": search_mode,
        "source_scope_mode": payload.source_scope.mode
        if payload.source_scope is not None
        else payload.scope_mode,
        "source_scope_label": source_scope_result.label,
        "retrieval_profile_name": profile_name,
        "retrieval_profile_scope": retrieval_profile_scope,
        "retrieval_profile_source": rag_profile_source,
        "retrieval_filters": retrieval_filters,
        "rerank_applied": rerank_applied,
        "rerank_provider": getattr(rerank_diagnostics, "provider_key", None)
        if rerank_diagnostics is not None
        else None,
        "rerank_model": getattr(rerank_diagnostics, "model_name", None)
        if rerank_diagnostics is not None
        else None,
        "rerank_score_min": rerank_score_min,
        "rerank_score_max": rerank_score_max,
        "rerank_fallback_used": rerank_fallback_used,
        "rerank_fallback_reason": rerank_fallback_reason,
        "request_id": request_id,
        "trace_request_id": request_id,
        "parallel_branch_count": len(parallel_branches),
        "parallel_branch_failure_count": sum(
            1 for branch in parallel_branches if not branch.succeeded
        ),
        "parallel_branch_timeout_count": sum(
            1 for branch in parallel_branches if branch.error_code == "timeout"
        ),
        "parallel_branches": parallel_branches,
    }
