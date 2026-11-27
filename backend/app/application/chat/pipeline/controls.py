"""Per-request controls of the chat pipeline: feature resolution, rerank, prompt, graph (R05-01)."""

from typing import Any
from uuid import UUID

from fastapi import (
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.errors import _safe_http_error
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.chat.services.conflict_detection_service import (
    ConflictDetectionChunk,
)
from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievalResult,
)
from app.domains.chat.services.prompt_service import PromptContextChunk
from app.domains.chat.services.rerank_service import (
    RerankCandidate,
    RerankResult,
    RerankSettings,
)
from app.domains.chat.services.retrieved_chunk import (
    RetrievedChunk,
    _merge_retrieved_chunks,
    _to_graph_retrieved_chunk,
)
from app.domains.chat.services.source_freshness_service import (
    DocumentTrustData,
)
from app.domains.prompt_templates.services.rendering import PromptTemplateValidationError
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig
from app.models.enums import PromptTemplateKey
from app.models.prompt_template import PromptTemplateVersion

_NOT_FOUND_ANSWER = "I could not find this information in the uploaded documents."
_feature_flag_service = default_deps.feature_flag_service
_graph_retrieval_service = default_deps.graph_retrieval_service
_prompt_service = default_deps.prompt_service
_prompt_template_service = default_deps.prompt_template_service
_rerank_service = default_deps.rerank_service
_source_freshness_service = default_deps.source_freshness_service


def _resolve_grounded_verification_controls(
    *,
    effective_policy: Any,
    rag_profile: RagProfileConfig | None,
) -> tuple[bool, str, float]:
    """Resolve grounded-verification activation and strictness.

    Collection/org policy can elevate verification for sensitive workspaces.
    When no policy override is set, fall back to the RAG profile config.
    """

    enabled = settings.feature_enable_grounded_answer_verification
    mode: str = "standard"
    threshold = 0.7

    if rag_profile is not None:
        enabled = rag_profile.grounded_answer_verification_enabled
        mode = rag_profile.grounded_answer_verification_mode
        threshold = rag_profile.grounded_answer_verification_threshold

    policy_mode = getattr(effective_policy, "grounded_verification_mode", "off")
    if policy_mode != "off":
        enabled = True
        mode = policy_mode
        policy_threshold = getattr(effective_policy, "grounded_verification_threshold", None)
        if policy_threshold is not None:
            threshold = policy_threshold

    return enabled, mode, threshold


def _resolve_planner_critic_controls(
    rag_profile: RagProfileConfig | None,
) -> tuple[bool, str, frozenset[str]]:
    """Resolve planner-critic-refiner activation, mode, and high-risk strategy set.

    Returns (enabled, mode, high_risk_strategies).
    """
    enabled: bool = settings.feature_enable_planner_critic_refiner
    mode: str = settings.planner_critic_refiner_mode
    high_risk: frozenset[str] = frozenset({"legal_compliance", "policy_lookup", "comparison"})

    if rag_profile is not None:
        enabled = rag_profile.planner_critic_refiner_enabled
        mode = rag_profile.planner_critic_refiner_mode
        if rag_profile.planner_high_risk_strategies:
            high_risk = frozenset(rag_profile.planner_high_risk_strategies)

    return enabled, mode, high_risk


async def _resolve_tree_search_reasoning_enabled(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> bool:
    try:
        return await _feature_flag_service.is_enabled(
            db_session,
            organization_id=organization_id,
            flag_name="tree_search_reasoning",
        )
    except Exception as exc:
        log_query_event(
            event="query.tree_search.feature_flag_fallback",
            organization_id=str(organization_id),
            error=exc.__class__.__name__,
            detail=str(exc),
            enabled=settings.feature_enable_tree_search_reasoning,
        )
        return settings.feature_enable_tree_search_reasoning


async def _rerank_chunks(
    *,
    query: str,
    chunks: list[RetrievedChunk],
    enabled: bool,
    final_top_k: int,
    settings_override: RerankSettings | None = None,
) -> tuple[list[RetrievedChunk], RerankResult]:
    if final_top_k < 1 or not chunks:
        empty_result = await _rerank_service.rerank(
            query=query,
            candidates=[],
            enabled=enabled,
            final_top_k=final_top_k,
            settings_override=settings_override,
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

    rerank_result: RerankResult = await _rerank_service.rerank(
        query=query,
        candidates=rerank_inputs,
        enabled=enabled,
        final_top_k=final_top_k,
        settings_override=settings_override,
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
                retrieval_source=source_chunk.retrieval_source,
                graph_score=source_chunk.graph_score,
                graph_hops=source_chunk.graph_hops,
                keyword_score=source_chunk.keyword_score,
                hybrid_score=source_chunk.hybrid_score,
                chunk_type=source_chunk.chunk_type,
                chunk_level=source_chunk.chunk_level,
                parent_text=source_chunk.parent_text,
            )
        )
    return selected_chunks, rerank_result


def _build_prompt(
    *,
    question: str,
    chunks: list[RetrievedChunk],
    parent_context_map: dict[str, str] | None = None,
    conflict_context: str = "",
    answer_language: str | None = None,
    template: str | None = None,
) -> str:
    _ctx = parent_context_map or {}
    return _prompt_service.build_prompt(
        question=question,
        not_found_answer=_NOT_FOUND_ANSWER,
        conflict_context=conflict_context,
        answer_language=answer_language,
        template=template,
        chunks=[
            PromptContextChunk(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=_ctx.get(str(chunk.chunk_id)) or chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=chunk.original_rank,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
            )
            for chunk in chunks
        ],
    )


def _build_conflict_detection_chunks(
    *,
    chunks: list[RetrievedChunk],
    parent_context_map: dict[str, str] | None,
    trust_map: dict[str, DocumentTrustData],
    org_stale_threshold_days: int | None,
) -> list[ConflictDetectionChunk]:
    context_map = parent_context_map or {}
    detection_chunks: list[ConflictDetectionChunk] = []
    for chunk in chunks:
        trust = trust_map.get(str(chunk.document_id))
        effective_trust_status = (
            _source_freshness_service.compute_effective_trust_status(
                trust,
                org_stale_threshold_days=org_stale_threshold_days,
            )
            if trust is not None
            else "current"
        )
        detection_chunks.append(
            ConflictDetectionChunk(
                chunk_id=str(chunk.chunk_id),
                document_id=str(chunk.document_id),
                text=context_map.get(str(chunk.chunk_id)) or chunk.text,
                similarity_score=chunk.similarity_score,
                trust_status=effective_trust_status,
            )
        )
    return detection_chunks


async def _resolve_answer_prompt_version(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> PromptTemplateVersion:
    try:
        return await _prompt_template_service.resolve_active_version(
            db_session,
            organization_id=organization_id,
            template_key=PromptTemplateKey.answer_generation.value,
        )
    except PromptTemplateValidationError as exc:
        raise _safe_http_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="prompt_template_unavailable",
            message="Answer prompt template is unavailable",
        ) from exc


def _build_rerank_settings(config: dict | None) -> RerankSettings:
    profile_config = RagProfileConfig.model_validate(config or {})
    return RerankSettings(
        enabled=profile_config.rerank_enabled if config is not None else True,
        provider_key=profile_config.rerank_provider,
        model_name=profile_config.rerank_model,
        timeout_seconds=profile_config.rerank_timeout_seconds,
        batch_size=profile_config.rerank_batch_size,
        max_input_candidates=profile_config.rerank_input_max_candidates,
        max_candidate_chars=profile_config.rerank_max_candidate_chars,
        fallback_behavior=profile_config.rerank_fallback_behavior,
    )


async def _resolve_graph_rag_enabled(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> bool:
    try:
        return await _feature_flag_service.is_enabled(
            db_session,
            organization_id=organization_id,
            flag_name="graph_rag",
        )
    except Exception as exc:
        log_query_event(
            event="query.graph.feature_flag_fallback",
            organization_id=str(organization_id),
            error=exc.__class__.__name__,
            detail=str(exc),
            enabled=settings.feature_enable_graph_rag,
        )
        return settings.feature_enable_graph_rag


async def _resolve_query_rewrite_preview_enabled(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> bool:
    try:
        return await _feature_flag_service.is_enabled(
            db_session,
            organization_id=organization_id,
            flag_name="query_rewrite_preview",
        )
    except Exception as exc:
        log_query_event(
            event="query.rewrite_preview.feature_flag_fallback",
            organization_id=str(organization_id),
            error=exc.__class__.__name__,
            detail=str(exc),
            enabled=settings.feature_enable_query_rewrite_preview,
        )
        return settings.feature_enable_query_rewrite_preview


async def _augment_retrieval_with_graph_context(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    question: str,
    vector_chunks: list[RetrievedChunk],
    allowed_document_ids: list[UUID] | None,
    graph_enabled: bool,
    graph_result: GraphRetrievalResult | None = None,
) -> tuple[list[RetrievedChunk], GraphRetrievalResult]:
    if not graph_enabled:
        return vector_chunks, GraphRetrievalResult(
            graph_context_enabled=False,
            graph_context_used=False,
            graph_context_reason="disabled",
        )

    if graph_result is None:
        graph_result = await _graph_retrieval_service.expand(
            session=db_session,
            organization_id=organization_id,
            question=question,
            allowed_document_ids=allowed_document_ids,
            graph_enabled=True,
        )
    if not graph_result.chunks:
        return vector_chunks, graph_result

    graph_chunks = [_to_graph_retrieved_chunk(chunk) for chunk in graph_result.chunks]
    return _merge_retrieved_chunks(vector_chunks, graph_chunks), graph_result
