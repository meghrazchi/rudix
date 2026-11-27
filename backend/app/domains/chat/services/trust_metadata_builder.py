"""Assembles the versioned answer trust metadata snapshot (R05-01)."""

from datetime import datetime
from uuid import UUID

from app.core.config import settings
from app.domains.chat.schemas.chat import (
    ChatCitationResponse,
)
from app.domains.chat.schemas.trust_metadata import (
    AnswerTrustMetadataResponse,
    CitationTrustRecord,
    ConfidenceReasonRecord,
    ConfidenceTrustRecord,
    ConflictStatusRecord,
    GroundedVerificationRecord,
    ModelMetadataRecord,
    PolicyEnforcementRecord,
    RetrievalDiagnosticsRecord,
    SourceFreshnessRecord,
)
from app.domains.chat.services.answer_critic_service import CriticResult
from app.domains.chat.services.answer_mode_service import (
    AnswerModeResult,
)
from app.domains.chat.services.answer_planner_service import (
    PlannerResult,
)
from app.domains.chat.services.answer_refiner_service import RefinerResult
from app.domains.chat.services.chat_values import _list_or_empty
from app.domains.chat.services.citation_enrichment import _source_freshness_service
from app.domains.chat.services.confidence_calibration import (
    _build_evidence_quality_record,
)
from app.domains.chat.services.conflict_detection_service import (
    ConflictDetectionResult,
)
from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievalResult,
)
from app.domains.chat.services.grounded_answer_verifier import (
    GroundedVerifierResult,
)
from app.domains.chat.services.query_intent_service import (
    _build_query_interpretation_record,
)
from app.domains.chat.services.retrieval_strategy_router import (
    RetrievalRouteResult,
)
from app.domains.chat.services.tool_orchestrator import (
    ToolOrchestrationResult,
)
from app.domains.chat.services.trust_records import (
    _build_claim_support_records,
    _build_planner_critic_record,
    _build_retrieval_method_record,
    _build_tool_orchestration_record,
)
from app.models.enums import PromptTemplateKey


def _build_trust_metadata(
    *,
    organization_id: UUID,
    message_id: str,
    question: str,
    query_rewrite_preview_enabled: bool,
    not_found: bool,
    citation_validation_failed: bool,
    verification_failed: bool,
    confidence_score: float,
    confidence_category: str,
    confidence_explanation: object,
    citations: list[ChatCitationResponse],
    retrieval_diagnostics_payload: dict[str, object],
    retrieved_chunks: list,
    selected_chunks: list,
    rerank_applied: bool,
    rerank_diagnostics: object | None,
    hybrid_vector_hit_count: int,
    hybrid_keyword_hit_count: int,
    query_rewrite_result: object | None,
    parent_context_expanded_count: int,
    graph_context_result: GraphRetrievalResult,
    freshness_excluded_count: int,
    freshness_boosted_count: int,
    freshness_stale_count: int,
    freshness_unreviewed_count: int,
    freshness_deprecated_count: int,
    freshness_draft_count: int,
    freshness_all_excluded_fallback: bool,
    grounded_verifier_result: GroundedVerifierResult | None,
    answer_mode_result: AnswerModeResult,
    llm_model: str | None,
    llm_provider: str | None,
    embedding_model: str | None,
    llm_fallback_used: bool,
    llm_fallback_from: str | None,
    llm_fallback_to: str | None,
    llm_fallback_reason: str | None,
    answer_prompt_version: object | None,
    conflict_detection_result: ConflictDetectionResult,
    ai_policy_applied: bool,
    ai_policy_result: object,
    generated_at: datetime,
    planner_result: "PlannerResult | None" = None,
    critic_result: "CriticResult | None" = None,
    refiner_result: "RefinerResult | None" = None,
    route_result: "RetrievalRouteResult | None" = None,
    orchestration_result: "ToolOrchestrationResult | None" = None,
) -> AnswerTrustMetadataResponse:
    """Build the versioned trust metadata contract from pipeline state.

    Never includes raw prompts, chain-of-thought, ACL snapshots, or internal
    version UUIDs — only user-facing fields that the trust panel needs.
    """
    expl = confidence_explanation

    source_freshness_warning = freshness_all_excluded_fallback or any(
        getattr(c, "doc_stale_warning", False)
        or getattr(c, "doc_expired_warning", False)
        or getattr(c, "doc_is_excluded_status", False)
        or getattr(c, "doc_unreviewed_warning", False)
        or getattr(c, "doc_deprecated_warning", False)
        or getattr(c, "doc_draft_warning", False)
        for c in citations
    )

    citation_records = [
        CitationTrustRecord(
            document_id=c.document_id,
            chunk_id=c.chunk_id,
            filename=c.filename,
            page_number=c.page_number,
            score=c.score,
            similarity_score=c.similarity_score,
            rerank_score=c.rerank_score,
            original_rank=c.original_rank,
            final_rank=c.final_rank,
            text_snippet=c.text_snippet,
            source_provider=c.source_provider,
            source_provider_label=c.source_provider_label,
            source_title=c.source_title,
            source_key=c.source_key,
            source_section=c.source_section,
            source_deep_link=c.source_deep_link,
            source_last_synced_at=c.source_last_synced_at,
            source_trust_status=c.source_trust_status,
            conflict_status=c.conflict_status,
            doc_trust_status=c.doc_trust_status,
            doc_quality_state=getattr(c, "doc_quality_state", None),
            doc_review_status=c.doc_review_status,
            doc_version_label=c.doc_version_label,
            doc_review_due_date=c.doc_review_due_date,
            doc_expiry_date=c.doc_expiry_date,
            doc_stale_warning=c.doc_stale_warning,
            doc_expired_warning=c.doc_expired_warning,
            doc_is_excluded_status=c.doc_is_excluded_status,
            is_table_chunk=c.is_table_chunk,
            table_caption=c.table_caption,
            table_row_count=c.table_row_count,
            table_col_count=c.table_col_count,
            table_headers=list(c.table_headers),
            doc_ocr_quality_status=c.doc_ocr_quality_status,
            doc_ocr_low_confidence_warning=c.doc_ocr_low_confidence_warning,
            freshness_state=getattr(c, "freshness_state", None),
            doc_last_updated_at=getattr(c, "doc_last_updated_at", None),
            doc_review_owner_id=getattr(c, "doc_review_owner_id", None),
            doc_unreviewed_warning=getattr(c, "doc_unreviewed_warning", False),
            doc_deprecated_warning=getattr(c, "doc_deprecated_warning", False),
            doc_draft_warning=getattr(c, "doc_draft_warning", False),
            table_extraction_confidence=getattr(c, "table_extraction_confidence", None),
            table_low_confidence_warning=getattr(c, "table_low_confidence_warning", False),
            doc_extraction_quality=getattr(c, "doc_extraction_quality", None),
            doc_extraction_warning=getattr(c, "doc_extraction_warning", False),
            doc_processing_warning=getattr(c, "doc_processing_warning", False),
        )
        for c in ([] if not_found else citations)
    ]

    prompt_key: str | None = None
    prompt_ver: int | None = None
    if answer_prompt_version is not None:
        prompt_key = PromptTemplateKey.answer_generation.value
        prompt_ver = getattr(answer_prompt_version, "version_number", None)

    gv_applied = grounded_verifier_result is not None and grounded_verifier_result.applied
    query_interpretation = _build_query_interpretation_record(
        question=question,
        query_rewrite_result=query_rewrite_result,
        rewrite_preview_enabled=query_rewrite_preview_enabled,
        answer_mode_result=answer_mode_result,
    )

    return AnswerTrustMetadataResponse(
        schema_version="1",
        organization_id=str(organization_id),
        message_id=message_id,
        not_found=not_found,
        citation_validation_failed=citation_validation_failed,
        verification_failed=verification_failed,
        confidence=ConfidenceTrustRecord(
            score=confidence_score,
            category=confidence_category,
            trust_level=expl.trust_level,
            citation_support_score=expl.citation_support_score,
            citation_validation_score=expl.citation_validation_score,
            citation_coverage_score=expl.citation_coverage_score,
            retrieval_agreement_score=expl.retrieval_agreement_score,
            top_similarity=expl.top_similarity,
            average_similarity=expl.average_similarity,
            top_rerank_score=expl.top_rerank_score,
            raw_score=expl.raw_score,
            citation_validation_multiplier=expl.citation_validation_multiplier,
            not_found_penalty_multiplier=expl.not_found_penalty_multiplier,
            freshness_multiplier=expl.freshness_multiplier,
            ocr_quality_multiplier=expl.ocr_quality_multiplier,
            conflict_multiplier=expl.conflict_multiplier,
            table_quality_multiplier=expl.table_quality_multiplier,
            extraction_quality_multiplier=expl.extraction_quality_multiplier,
            graph_evidence_boost=expl.graph_evidence_boost,
            verification_support_score=expl.verification_support_score,
            not_found_signal=expl.not_found_signal,
            no_context=expl.no_context,
            reasons=[
                ConfidenceReasonRecord(
                    code=r.code,
                    label=r.label,
                    impact=r.impact,
                    magnitude=r.magnitude,
                )
                for r in expl.reasons
            ],
        ),
        citations=citation_records,
        retrieval=RetrievalDiagnosticsRecord(
            **retrieval_diagnostics_payload,
            hybrid_retrieval_enabled=settings.feature_enable_hybrid_retrieval,
            hybrid_vector_hit_count=hybrid_vector_hit_count,
            hybrid_keyword_hit_count=hybrid_keyword_hit_count,
            query_rewriting_applied=query_rewrite_result is not None
            and query_rewrite_result.rewriting_applied,
            query_decomposed=query_rewrite_result is not None
            and query_rewrite_result.decomposition_applied,
            sub_query_count=(
                len(query_rewrite_result.sub_queries) if query_rewrite_result is not None else 0
            ),
            parent_context_expanded_count=parent_context_expanded_count,
            graph_context_used=graph_context_result.graph_context_used,
            graph_context_unavailable=graph_context_result.graph_context_unavailable,
            graph_chunk_count=graph_context_result.graph_chunk_count,
            freshness_excluded_count=freshness_excluded_count,
            freshness_boosted_count=freshness_boosted_count,
        ),
        query_interpretation=query_interpretation,
        grounded_verification=GroundedVerificationRecord(
            applied=gv_applied,
            verdict=grounded_verifier_result.verdict if gv_applied else None,
            score=grounded_verifier_result.verification_score if gv_applied else None,
            aggregate_support_score=grounded_verifier_result.aggregate_support_score
            if grounded_verifier_result is not None
            else 0.0,
            claim_count=grounded_verifier_result.claim_count
            if grounded_verifier_result is not None
            else 0,
            supported_count=grounded_verifier_result.supported_claim_count
            if grounded_verifier_result is not None
            else 0,
            partially_supported_count=grounded_verifier_result.partially_supported_claim_count
            if grounded_verifier_result is not None
            else 0,
            unsupported_count=grounded_verifier_result.unsupported_claim_count
            if grounded_verifier_result is not None
            else 0,
            unverifiable_count=grounded_verifier_result.unverifiable_claim_count
            if grounded_verifier_result is not None
            else 0,
            conflicting_count=grounded_verifier_result.conflicting_claim_count
            if grounded_verifier_result is not None
            else 0,
            not_enough_evidence_count=grounded_verifier_result.not_enough_evidence_claim_count
            if grounded_verifier_result is not None
            else 0,
            removed_count=len(grounded_verifier_result.removed_claims)
            if grounded_verifier_result is not None
            else 0,
            reason_codes=list(grounded_verifier_result.reason_codes)
            if grounded_verifier_result is not None
            else [],
            claims=_build_claim_support_records(
                grounded_verifier_result=grounded_verifier_result if gv_applied else None
            ),
            mode=grounded_verifier_result.mode if grounded_verifier_result is not None else None,
            threshold=grounded_verifier_result.threshold
            if grounded_verifier_result is not None
            else None,
        ),
        model=ModelMetadataRecord(
            llm_model=llm_model,
            llm_provider=llm_provider,
            embedding_model=embedding_model,
            fallback_used=llm_fallback_used,
            fallback_from=llm_fallback_from,
            fallback_to=llm_fallback_to,
            fallback_reason=llm_fallback_reason,
            prompt_template_key=prompt_key,
            prompt_template_version=prompt_ver,
        ),
        conflict=ConflictStatusRecord(
            detected=conflict_detection_result.conflict_detected,
            agreement_level=conflict_detection_result.agreement_level,
            conflict_count=len(conflict_detection_result.conflict_pairs),
            conflicting_document_ids=_list_or_empty(
                conflict_detection_result.conflicting_document_ids
            ),
            preferred_document_ids=_list_or_empty(conflict_detection_result.preferred_document_ids),
            conflict_summary=conflict_detection_result.conflict_summary
            if conflict_detection_result.conflict_detected
            else None,
        ),
        policy=PolicyEnforcementRecord(
            applied=ai_policy_applied,
            outcome=getattr(ai_policy_result, "outcome", None) if ai_policy_applied else None,
            violated_rules=list(getattr(ai_policy_result, "violated_rules", []) or []),
            warning_flags=list(getattr(ai_policy_result, "warning_flags", []) or []),
            has_disclaimer=bool(getattr(ai_policy_result, "disclaimer_text", None))
            if ai_policy_applied
            else False,
        ),
        freshness=SourceFreshnessRecord(
            warning=source_freshness_warning,
            warning_reason="One or more citations come from stale, draft, unreviewed, deprecated, or archived sources."
            if source_freshness_warning
            else None,
            warning_reasons=_source_freshness_service.build_warning_reasons(
                stale_count=freshness_stale_count,
                excluded_count=freshness_excluded_count,
                unreviewed_count=freshness_unreviewed_count,
                deprecated_count=freshness_deprecated_count,
                draft_count=freshness_draft_count,
                all_excluded_fallback=freshness_all_excluded_fallback,
            ),
            stale_count=freshness_stale_count,
            excluded_count=freshness_excluded_count,
            boosted_count=freshness_boosted_count,
            unreviewed_count=freshness_unreviewed_count,
            deprecated_count=freshness_deprecated_count,
            draft_count=freshness_draft_count,
            all_excluded_fallback=freshness_all_excluded_fallback,
        ),
        evidence_quality=_build_evidence_quality_record(citation_records),
        planner_critic=_build_planner_critic_record(
            planner_result=planner_result,
            critic_result=critic_result,
            refiner_result=refiner_result,
        ),
        retrieval_method=_build_retrieval_method_record(route_result),
        tool_orchestration=_build_tool_orchestration_record(orchestration_result),
        generated_at=generated_at,
    )
