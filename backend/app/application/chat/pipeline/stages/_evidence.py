"""Evidence adjustments applied to retrieved chunks before reranking (R05-01).

Source freshness filtering and trust boosting (F297/F311), table-aware boosting (F298), and
OCR quality downranking (F299), in the order ``query_chat`` applied them.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.context import ChatContext
from app.core.config import settings
from app.domains.chat.services.retrieved_chunk import RetrievedChunk
from app.domains.chat.services.table_retrieval_service import is_table_query
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig


def _rescored(chunk: RetrievedChunk, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        filename=chunk.filename,
        page_number=chunk.page_number,
        text=chunk.text,
        similarity_score=score,
        original_rank=chunk.original_rank,
        rerank_score=chunk.rerank_score,
        rerank_rank=chunk.rerank_rank,
        final_rank=chunk.final_rank,
        retrieval_source=chunk.retrieval_source,
        graph_score=chunk.graph_score,
        graph_hops=chunk.graph_hops,
        keyword_score=chunk.keyword_score,
        hybrid_score=chunk.hybrid_score,
        chunk_type=chunk.chunk_type,
        chunk_level=chunk.chunk_level,
        parent_text=chunk.parent_text,
    )


def _profile_config(ctx: ChatContext) -> RagProfileConfig | None:
    rag_profile = ctx.config.rag_profile
    if rag_profile is None:
        return None
    return RagProfileConfig.model_validate(dict(rag_profile.config))


async def apply_freshness(ctx: ChatContext, db_session: AsyncSession) -> None:
    """Source freshness filtering and trust-score boosting (F297). Defaults are safe."""
    ret = ctx.retrieval
    freshness = ctx.deps.source_freshness_service
    boost_enabled = True
    exclude_deprecated = True
    exclude_expired = True
    stale_threshold_days: int | None = None
    profile_cfg = _profile_config(ctx)
    if profile_cfg is not None:
        boost_enabled = profile_cfg.freshness_boost_enabled
        exclude_deprecated = profile_cfg.exclude_deprecated_docs
        exclude_expired = profile_cfg.exclude_expired_docs
        stale_threshold_days = profile_cfg.stale_threshold_days
    ret.freshness_stale_threshold_days = stale_threshold_days

    ret.freshness_filter_enabled = boost_enabled or exclude_deprecated or exclude_expired
    if not (ret.freshness_filter_enabled and ret.retrieved_chunks):
        return
    unique_doc_ids = list({chunk.document_id for chunk in ret.retrieved_chunks})
    trust_docs = await ctx.deps.document_repository_for_trust.get_documents_by_ids_for_trust(
        db_session,
        document_ids=unique_doc_ids,
        organization_id=ctx.request.organization_id,
    )
    ret.freshness_trust_map = freshness.build_trust_map(trust_docs)  # type: ignore[arg-type]

    if exclude_deprecated or exclude_expired:
        filter_result = freshness.filter_excluded(
            chunk_document_ids=[str(c.document_id) for c in ret.retrieved_chunks],
            trust_map=ret.freshness_trust_map,
            exclude_deprecated=exclude_deprecated,
            exclude_expired=exclude_expired,
            org_stale_threshold_days=stale_threshold_days,
        )
        ret.freshness_excluded_count = filter_result.excluded_count
        ret.freshness_stale_ids = filter_result.stale_document_ids
        ret.freshness_stale_count = len(ret.freshness_stale_ids)
        if filter_result.excluded_document_ids:
            before_exclusion = ret.retrieved_chunks
            after_exclusion = [
                c
                for c in ret.retrieved_chunks
                if str(c.document_id) not in filter_result.excluded_document_ids
            ]
            # F311: if exclusion empties the context, fall back to the excluded chunks
            # with a warning.
            ret.retrieved_chunks, ret.freshness_all_excluded_fallback = (
                freshness.apply_exclusion_fallback(
                    after_filter=after_exclusion,
                    before_filter=before_exclusion,
                    excluded_ids=filter_result.excluded_document_ids,
                )
            )

    if boost_enabled and ret.freshness_trust_map:
        adjusted: list[RetrievedChunk] = []
        for chunk in ret.retrieved_chunks:
            new_score = freshness.apply_trust_score_multiplier(
                score=chunk.similarity_score,
                document_id=str(chunk.document_id),
                trust_map=ret.freshness_trust_map,
                org_stale_threshold_days=stale_threshold_days,
            )
            if new_score != chunk.similarity_score:
                ret.freshness_boosted_count += 1
            adjusted.append(_rescored(chunk, new_score))
        ret.retrieved_chunks = sorted(adjusted, key=lambda c: c.similarity_score, reverse=True)


def apply_table_boost(ctx: ChatContext) -> None:
    """Table-aware retrieval boost (F298), after freshness scoring and before reranking."""
    ret = ctx.retrieval
    if not (settings.feature_enable_table_aware_retrieval and ret.retrieved_chunks):
        return
    table_boost_enabled = True
    table_boost_multiplier = settings.table_retrieval_boost_multiplier
    profile_cfg = _profile_config(ctx)
    if profile_cfg is not None:
        table_boost_enabled = profile_cfg.table_retrieval_boost_enabled
        table_boost_multiplier = profile_cfg.table_retrieval_boost_multiplier
    ret.table_boost_enabled = table_boost_enabled
    ret.retrieved_chunks, ret.table_boost_result = (
        ctx.deps.table_retrieval_service.apply_table_boost(
            chunks=ret.retrieved_chunks,
            query=ctx.request.payload.question,
            boost_multiplier=table_boost_multiplier,
            enabled=table_boost_enabled,
        )
    )
    if ret.table_boost_result is not None:
        ret.table_boost_applied = ret.table_boost_result.boost_applied
        ret.table_boost_count = ret.table_boost_result.boosted_count
        ret.table_chunk_count = ret.table_boost_result.table_chunk_count
        ret.table_query_detected = is_table_query(ctx.request.payload.question)
        if ret.table_boost_applied:
            ret.retrieved_chunks = sorted(
                ret.retrieved_chunks, key=lambda c: c.similarity_score, reverse=True
            )


async def apply_ocr_quality(ctx: ChatContext, db_session: AsyncSession) -> None:
    """OCR quality downranking (F299): low or failed OCR text ranks below clean text."""
    ret = ctx.retrieval
    if not (settings.feature_enable_ocr_quality_downranking and ret.retrieved_chunks):
        return
    ocr = ctx.deps.ocr_quality_service
    ret.ocr_quality_downranking_enabled = True
    ocr_doc_ids = list({chunk.document_id for chunk in ret.retrieved_chunks})
    ocr_docs: list[
        Any
    ] = await ctx.deps.document_repository_for_trust.get_documents_by_ids_for_trust(
        db_session,
        document_ids=ocr_doc_ids,
        organization_id=ctx.request.organization_id,
    )
    ret.ocr_docs = ocr_docs
    ret.ocr_quality_map = ocr.build_quality_map(ocr_docs)
    if not ret.ocr_quality_map:
        return
    adjusted: list[RetrievedChunk] = []
    for chunk in ret.retrieved_chunks:
        new_score = ocr.apply_quality_score(
            score=chunk.similarity_score,
            document_id=str(chunk.document_id),
            quality_map=ret.ocr_quality_map,
        )
        if ocr.is_low_confidence(ret.ocr_quality_map.get(str(chunk.document_id))):
            ret.ocr_low_confidence_chunk_count += 1
        adjusted.append(_rescored(chunk, new_score))
    ret.retrieved_chunks = sorted(adjusted, key=lambda c: c.similarity_score, reverse=True)
