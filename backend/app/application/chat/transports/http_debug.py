"""The ``debug`` block of ``ChatQueryResponse`` built from a finished chat run (R05-01).

``ChatDebugResponse`` ignores unknown fields, so the legacy ``freshness_draft_count`` keyword
is not passed; the response is unchanged.
"""

from typing import cast

from app.application.chat.pipeline.context import ChatContext
from app.core.config import settings
from app.domains.chat.schemas.chat import ChatDebugResponse
from app.domains.chat.services.chat_values import _decimal_to_float_or_none, _list_or_empty
from app.models.enums import PromptTemplateKey


def build_debug_response(ctx: ChatContext) -> ChatDebugResponse:
    ret = ctx.retrieval
    gen = ctx.generation
    ver = ctx.verification
    cfg = ctx.config
    out = ctx.persist
    rerank = out.rerank_diagnostics
    graph = ret.graph_context_result
    conflict = ret.conflict_detection_result
    rewrite = cfg.query_rewrite_result
    gv = ver.grounded_verifier_result
    version = cfg.answer_prompt_version
    assert ctx.scope.source_scope_result is not None and cfg.rerank_settings is not None
    gv_applied = gv is not None and gv.applied
    return ChatDebugResponse(
        latencies_ms=ctx.latencies_ms,
        **out.retrieval_diagnostics_payload,
        source_scope=ctx.scope.source_scope_result.label,
        rerank_enabled=cfg.rerank_settings.enabled,
        rerank_input_count=rerank.requested_count if rerank else 0,
        rerank_batch_count=rerank.batch_count if rerank else 0,
        rerank_prompt_tokens=rerank.prompt_tokens if rerank else 0,
        rerank_completion_tokens=rerank.completion_tokens if rerank else 0,
        rerank_total_tokens=rerank.total_tokens if rerank else 0,
        rerank_cost_usd=_decimal_to_float_or_none(rerank.approximate_cost_usd) if rerank else None,
        graph_context_enabled=graph.graph_context_enabled,
        graph_context_used=graph.graph_context_used,
        graph_context_unavailable=graph.graph_context_unavailable,
        graph_context_reason=graph.graph_context_reason,
        graph_seed_entity_count=graph.graph_seed_entity_count,
        graph_related_entity_count=graph.graph_related_entity_count,
        graph_chunk_count=graph.graph_chunk_count,
        graph_max_hops_used=graph.graph_max_hops_used,
        conflict_detection_enabled=ret.conflict_detection_enabled,
        conflict_detection_applied=ret.conflict_detection_applied,
        conflict_detection_latency_ms=ret.conflict_detection_latency_ms,
        conflict_detection_agreement_level=conflict.agreement_level,
        conflict_detection_conflict_count=len(conflict.conflict_pairs),
        conflict_detection_conflicting_document_ids=list(conflict.conflicting_document_ids),
        conflict_detection_preferred_document_ids=list(conflict.preferred_document_ids),
        conflict_detection_model=conflict.model_name or None,
        conflict_detection_provider=conflict.provider_key or None,
        graph_relation_types_used=cast(list[str], _list_or_empty(graph.graph_relation_types_used)),
        embedding_model=ret.embedding_model,
        llm_model=gen.llm_model,
        llm_provider=gen.llm_provider,
        fallback_used=gen.llm_fallback_used,
        fallback_from=gen.llm_fallback_from,
        fallback_to=gen.llm_fallback_to,
        fallback_reason=gen.llm_fallback_reason,
        detected_language=cfg.detected_language,
        answer_language_used=cfg.answer_language_used,
        prompt_template_key=PromptTemplateKey.answer_generation.value
        if version is not None
        else None,
        prompt_template_version=version.version_number if version is not None else None,
        prompt_template_version_id=str(version.id) if version is not None else None,
        hybrid_retrieval_enabled=ret.hybrid_retrieval_enabled,
        hybrid_vector_hit_count=ret.hybrid_vector_hit_count,
        hybrid_keyword_hit_count=ret.hybrid_keyword_hit_count,
        hybrid_exact_match_tokens=ret.hybrid_exact_match_tokens,
        query_rewriting_enabled=settings.feature_enable_query_rewriting,
        query_rewriting_applied=rewrite.rewriting_applied if rewrite is not None else False,
        query_decomposed=rewrite.decomposition_applied if rewrite is not None else False,
        original_query=rewrite.original_query if rewrite is not None else None,
        rewritten_query=rewrite.primary_query
        if rewrite is not None and rewrite.rewriting_applied
        else None,
        sub_queries=list(rewrite.sub_queries) if rewrite is not None else [],
        query_rewriting_strategy=rewrite.strategy if rewrite is not None else None,
        query_rewriting_latency_ms=rewrite.latency_ms if rewrite is not None else 0,
        grounded_verification_enabled=ver.grounded_verification_enabled,
        grounded_verification_applied=gv.applied if gv is not None else False,
        grounded_verification_verdict=gv.verdict if gv is not None and gv_applied else None,
        grounded_verification_score=gv.verification_score
        if gv is not None and gv_applied
        else None,
        grounded_verification_claim_count=gv.claim_count if gv is not None else 0,
        grounded_verification_supported_count=gv.supported_claim_count if gv is not None else 0,
        grounded_verification_partially_supported_count=gv.partially_supported_claim_count
        if gv is not None
        else 0,
        grounded_verification_unsupported_count=gv.unsupported_claim_count if gv is not None else 0,
        grounded_verification_unverifiable_count=gv.unverifiable_claim_count
        if gv is not None
        else 0,
        grounded_verification_conflicting_count=gv.conflicting_claim_count if gv is not None else 0,
        grounded_verification_not_enough_evidence_count=gv.not_enough_evidence_claim_count
        if gv is not None
        else 0,
        grounded_verification_removed_count=len(gv.removed_claims) if gv is not None else 0,
        grounded_verification_reason_codes=list(gv.reason_codes) if gv is not None else [],
        grounded_verification_mode=gv.mode if gv is not None else ver.grounded_verification_mode,
        grounded_verification_threshold=gv.threshold
        if gv is not None
        else ver.grounded_verification_threshold,
        grounded_verification_model=gv.model_name if gv is not None and gv_applied else None,
        grounded_verification_latency_ms=gv.latency_ms if gv is not None else 0,
        freshness_filter_enabled=ret.freshness_filter_enabled,
        freshness_excluded_count=ret.freshness_excluded_count,
        freshness_boosted_count=ret.freshness_boosted_count,
        freshness_stale_count=ret.freshness_stale_count,
        freshness_unreviewed_count=ret.freshness_unreviewed_count,
        freshness_deprecated_count=ret.freshness_deprecated_count,
        freshness_all_excluded_fallback=ret.freshness_all_excluded_fallback,
        table_boost_enabled=ret.table_boost_enabled,
        table_boost_applied=ret.table_boost_applied,
        table_boost_count=ret.table_boost_count,
        table_chunk_count=ret.table_chunk_count,
        table_query_detected=ret.table_query_detected,
        ocr_quality_downranking_enabled=ret.ocr_quality_downranking_enabled,
        ocr_low_confidence_chunk_count=ret.ocr_low_confidence_chunk_count,
        parent_context_expansion_enabled=ret.parent_context_expansion_enabled,
        parent_context_child_hit_count=ret.parent_context_child_hit_count,
        parent_context_expanded_count=ret.parent_context_expanded_count,
        parent_context_tokens_used=ret.parent_context_tokens_used,
    )
