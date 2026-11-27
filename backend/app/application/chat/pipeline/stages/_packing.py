"""Context injection scan (R05-09), strict context packing (F340), and parent-context
expansion (F300) (R05-01)."""

from app.application.chat.pipeline.context import ChatContext
from app.core.config import settings
from app.core.logging import log_query_event
from app.core.metrics import record_chat_context_injection_flagged
from app.domains.chat.services.context_injection_scan import scan_retrieved_chunks
from app.domains.chat.services.context_packer_service import ContextPackerConfig
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig


def apply_context_injection_scan(ctx: ChatContext) -> None:
    """Scan the reranked chunks for prompt-injection patterns and flag, down-rank, or drop
    the matches (``CHAT_CONTEXT_INJECTION_ACTION``). Logs counts only, never text."""
    ret = ctx.retrieval
    if not ret.selected_chunks:
        return
    result = scan_retrieved_chunks(
        ret.selected_chunks,
        action=settings.chat_context_injection_action,
        downrank_multiplier=settings.chat_context_injection_downrank_multiplier,
    )
    ctx.context_injection = result
    if not result.flagged_count:
        return
    ret.selected_chunks = result.chunks
    record_chat_context_injection_flagged(result.action, result.flagged_count)
    log_query_event(
        event="chat.context.injection_flagged",
        organization_id=ctx.request.principal.organization_id,
        user_id=ctx.request.principal.user_id,
        job_id=ctx.job_id,
        action=result.action,
        flagged_count=result.flagged_count,
        selected_count=len(ret.selected_chunks),
    )


def apply_context_packing(ctx: ChatContext) -> None:
    """Priority score, rejection rules, and a global token budget over the reranked chunks.

    Controlled by the RAG profile; ``feature_enable_context_packing`` must also be on.
    """
    ret = ctx.retrieval
    if not (settings.feature_enable_context_packing and ret.selected_chunks):
        return
    packer_cfg = ContextPackerConfig(enabled=True)
    rag_profile = ctx.config.rag_profile
    if rag_profile is not None:
        rag_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
        packer_cfg = ContextPackerConfig(
            enabled=rag_cfg.context_packing_enabled,
            strategy=rag_cfg.context_packing_strategy,
            budget_max_tokens=rag_cfg.context_budget_max_tokens,
            min_relevance_score=rag_cfg.context_min_relevance_score,
            reject_weak_ocr=rag_cfg.context_reject_weak_ocr,
            reject_stale_superseded=rag_cfg.context_reject_stale_superseded,
            require_citations=rag_cfg.context_require_citations,
            not_found_min_chunks=rag_cfg.context_not_found_min_chunks,
        )
    # Build a freshness state map from the trust data already loaded.
    freshness_state_map: dict[str, str] = {}
    for doc_id, trust_data in ret.freshness_trust_map.items():
        freshness_state_map[doc_id] = ctx.deps.source_freshness_service.derive_freshness_state(
            trust_data,
            org_stale_threshold_days=ret.freshness_stale_threshold_days,
        )
    pack_result = ctx.deps.context_packer_service.pack(
        chunks=ret.selected_chunks,
        config=packer_cfg,
        ocr_quality_map=ret.ocr_quality_map if ret.ocr_quality_map else None,
        freshness_state_map=freshness_state_map if freshness_state_map else None,
    )
    ret.context_pack_result = pack_result
    ret.context_packing_rejected_count = len(pack_result.rejected)
    if pack_result.selected is not ret.selected_chunks:
        ret.selected_chunks = pack_result.selected
    if ret.context_packing_rejected_count:
        log_query_event(
            event="query.context_packing.applied",
            organization_id=ctx.request.principal.organization_id,
            user_id=ctx.request.principal.user_id,
            job_id=ctx.job_id,
            strategy=packer_cfg.strategy,
            selected_count=len(ret.selected_chunks),
            rejected_count=ret.context_packing_rejected_count,
            rejected_low_relevance=pack_result.rejected_low_relevance,
            rejected_weak_ocr=pack_result.rejected_weak_ocr,
            rejected_stale_superseded=pack_result.rejected_stale_superseded,
            rejected_token_budget=pack_result.rejected_token_budget,
            total_estimated_tokens=pack_result.total_estimated_tokens,
            budget_applied=pack_result.budget_applied,
        )


def apply_parent_context_expansion(ctx: ChatContext) -> None:
    """Substitute parent sections into the prompt; citations keep the precise child chunk."""
    ret = ctx.retrieval
    if not (settings.feature_enable_parent_context_expansion and ret.selected_chunks):
        return
    enabled = True
    max_tokens = settings.parent_context_max_tokens_per_chunk
    rag_profile = ctx.config.rag_profile
    if rag_profile is not None:
        profile_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
        enabled = profile_cfg.parent_context_expansion_enabled
        max_tokens = profile_cfg.parent_context_max_tokens_per_chunk
    expansion = ctx.deps.parent_context_expansion_service.expand(
        chunks=ret.selected_chunks,
        enabled=enabled,
        max_tokens_per_chunk=max_tokens,
    )
    ret.parent_expansion_result = expansion
    ret.parent_context_map = expansion.context_map
    ret.parent_context_expansion_enabled = expansion.expanded_count > 0
    ret.parent_context_child_hit_count = expansion.child_hit_count
    ret.parent_context_expanded_count = expansion.expanded_count
    ret.parent_context_tokens_used = expansion.tokens_used
    if ret.parent_context_expansion_enabled:
        log_query_event(
            event="query.parent_context.expanded",
            organization_id=ctx.request.principal.organization_id,
            user_id=ctx.request.principal.user_id,
            job_id=ctx.job_id,
            child_hit_count=ret.parent_context_child_hit_count,
            expanded_count=ret.parent_context_expanded_count,
            tokens_used=ret.parent_context_tokens_used,
        )
