"""Citation validation, enrichment, and calibrated confidence of a generated answer (R05-01).

Citations are rebuilt from the retrieved chunks; a model citation that names a chunk outside
the context is rejected (``citation_validation_failed``), never trusted.
"""

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.stages._tree_search import (
    context_chunks,
    empty_citation_result,
    log_citation_validation,
)
from app.domains.chat.schemas.chat import ChatCitationResponse
from app.domains.chat.services.chat_values import _parse_uuid_or_none
from app.domains.chat.services.citation_enrichment import (
    _with_conflict_status,
    _with_extraction_quality,
    _with_freshness,
    _with_ocr_quality,
    _with_provenance,
    _with_table_metadata,
)
from app.domains.chat.services.confidence_calibration import (
    _compute_conflict_multiplier,
    _compute_extraction_quality_multiplier,
    _compute_freshness_multiplier,
    _compute_ocr_quality_multiplier,
    _compute_table_quality_multiplier,
)


def build_answer_citations(ctx: ChatContext) -> None:
    """Validate the model's citations against the context chunks."""
    gen = ctx.generation
    if not gen.not_found:
        assert gen.llm_result is not None
        gen.citation_result = ctx.deps.citation_service.build_citations(
            not_found=False,
            answer=gen.answer,
            retrieved_chunks=context_chunks(ctx),
            model_citations=gen.llm_result.citations,
        )
    if gen.citation_result is None:
        gen.citation_result = empty_citation_result()


async def enrich_citations_and_score(ctx: ChatContext) -> None:
    """Attach provenance, freshness, table, OCR, conflict, and extraction data; then score."""
    req = ctx.request
    ret = ctx.retrieval
    gen = ctx.generation
    ver = ctx.verification
    citation_result = gen.citation_result
    assert citation_result is not None
    citation_chunk_ids = [
        chunk_id
        for citation in citation_result.citations
        if (chunk_id := _parse_uuid_or_none(citation.chunk_id)) is not None
    ]
    async with ctx.sessions.short() as db_session:
        provenance_by_chunk_id = await ctx.deps.source_provenance_service.load_citation_details(
            db_session,
            organization_id=req.organization_id,
            chunk_ids=citation_chunk_ids,
        )
        # Table metadata lookup (F298): fetch table_metadata for any table chunks.
        table_metadata_by_chunk_id = (
            await ctx.deps.document_repository_for_trust.get_chunks_table_metadata(
                db_session,
                chunk_ids=citation_chunk_ids,
                organization_id=req.organization_id,
            )
        )
    table_metadata_map = {str(k): v for k, v in table_metadata_by_chunk_id.items()}
    # F315: extraction quality from the already-loaded document objects.
    extraction_quality_map: dict[str, tuple[str | None, float | None, str]] = {
        str(doc.id): (
            (doc.extraction_snapshot or {}).get("document_profile"),
            (doc.extraction_snapshot or {}).get("extraction_confidence"),
            doc.status,
        )
        for doc in ret.ocr_docs
    }
    citations: list[ChatCitationResponse] = []
    for citation in citation_result.citations:
        citation_uuid = _parse_uuid_or_none(citation.chunk_id)
        citations.append(
            _with_extraction_quality(
                _with_conflict_status(
                    _with_ocr_quality(
                        _with_table_metadata(
                            _with_freshness(
                                _with_provenance(
                                    citation,
                                    provenance_by_chunk_id.get(citation_uuid),  # type: ignore[arg-type]
                                ),
                                ret.freshness_trust_map,
                                ret.freshness_stale_ids,
                            ),
                            table_metadata_map,
                        ),
                        {str(k): v for k, v in ret.ocr_quality_map.items()},
                    ),
                    ret.conflict_detection_result,
                ),
                extraction_quality_map,
            )
        )
    gen.citations = citations
    ver.citation_validation_failed = citation_result.invalid_chunk_id_count > 0
    # F311: per-freshness-state citation counts from the annotated citations.
    ret.freshness_unreviewed_count = sum(
        1 for c in citations if getattr(c, "doc_unreviewed_warning", False)
    )
    ret.freshness_deprecated_count = sum(
        1 for c in citations if getattr(c, "doc_deprecated_warning", False)
    )
    ret.freshness_draft_count = sum(1 for c in citations if getattr(c, "doc_draft_warning", False))
    ver.freshness_multiplier = _compute_freshness_multiplier(
        ret.freshness_stale_count, len(citations)
    )
    ver.ocr_quality_multiplier = _compute_ocr_quality_multiplier(citations)
    ver.conflict_multiplier = _compute_conflict_multiplier(ret.conflict_detection_result)
    # F315: evidence quality multipliers.
    table_quality_multiplier = _compute_table_quality_multiplier(citations)
    extraction_quality_multiplier = _compute_extraction_quality_multiplier(citations)
    result = ctx.deps.confidence_service.score(
        chunks=ver.confidence_signals,
        citation_count=len(citations),
        citation_validation_score=citation_result.validation_score,
        not_found_signal=False,
        freshness_multiplier=ver.freshness_multiplier,
        ocr_quality_multiplier=ver.ocr_quality_multiplier,
        conflict_multiplier=ver.conflict_multiplier,
        table_quality_multiplier=table_quality_multiplier,
        extraction_quality_multiplier=extraction_quality_multiplier,
        graph_context_used=ret.graph_context_result.graph_context_used,
    )
    ver.confidence_score = result.score
    ver.confidence_category = result.category
    ver.confidence_explanation = result.explanation
    log_citation_validation(ctx, citation_result)


def score_not_found(ctx: ChatContext) -> None:
    ver = ctx.verification
    result = ctx.deps.confidence_service.score(
        chunks=ver.confidence_signals,
        citation_count=0,
        citation_validation_score=1.0,
        not_found_signal=True,
        freshness_multiplier=ver.freshness_multiplier,
        ocr_quality_multiplier=ver.ocr_quality_multiplier,
        conflict_multiplier=ver.conflict_multiplier,
    )
    ver.confidence_score = result.score
    ver.confidence_category = result.category
    ver.confidence_explanation = result.explanation
