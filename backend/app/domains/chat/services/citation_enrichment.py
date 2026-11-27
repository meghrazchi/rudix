"""Citation enrichment with freshness, provenance, table, OCR, conflict, and extraction data (R05-01)."""

from typing import Any, Literal, cast

from app.domains.chat.schemas.chat import (
    ChatCitationResponse,
)
from app.domains.chat.services.confidence_calibration import (
    _EXTRACTION_CONFIDENCE_WARN_THRESHOLD,
    _EXTRACTION_WARNING_PROFILES,
    _PROCESSING_INCOMPLETE_STATUSES,
    _TABLE_CONFIDENCE_LOW_THRESHOLD,
)
from app.domains.chat.services.conflict_detection_service import (
    ConflictDetectionResult,
)
from app.domains.chat.services.source_freshness_service import (
    DocumentTrustData,
    SourceFreshnessService,
)
from app.domains.documents.services.ocr_quality_service import OcrQualityService

# The one instance of each service; the pipeline deps reuse them.
_source_freshness_service = SourceFreshnessService()
_ocr_quality_service = OcrQualityService()


def _with_freshness(
    citation: ChatCitationResponse,
    trust_map: dict[str, DocumentTrustData],
    stale_document_ids: frozenset[str],
) -> ChatCitationResponse:
    """Annotate a citation with document trust/freshness metadata (F297/F311)."""
    trust = trust_map.get(citation.document_id)
    if trust is None:
        return citation
    effective_status = _source_freshness_service.compute_effective_trust_status(trust)
    freshness_state = _source_freshness_service.derive_freshness_state(trust)
    is_stale = citation.document_id in stale_document_ids or effective_status in {
        "stale",
        "needs_review",
    }
    is_unreviewed = effective_status == "needs_review"
    is_deprecated = effective_status in {"archived", "deprecated", "superseded"}
    is_draft = effective_status == "draft" or trust.quality_state == "draft"
    return ChatCitationResponse(
        citation_id=citation.citation_id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=citation.conflict_status,
        doc_trust_status=trust.trust_status,
        doc_quality_state=trust.quality_state,
        doc_review_status=trust.review_status or trust.trust_status,
        doc_review_owner_id=str(trust.review_owner_id) if trust.review_owner_id else None,
        doc_review_due_date=trust.review_due_date,
        doc_expiry_date=trust.expiry_date,
        doc_version_label=trust.version_label,
        doc_review_date=trust.review_date,
        doc_effective_date=trust.effective_date,
        doc_stale_warning=is_stale,
        doc_expired_warning=effective_status == "expired",
        doc_is_excluded_status=effective_status
        in {"archived", "deprecated", "superseded", "expired"},
        freshness_state=freshness_state,
        doc_last_updated_at=trust.last_updated_at,
        doc_unreviewed_warning=is_unreviewed,
        doc_deprecated_warning=is_deprecated,
        doc_draft_warning=is_draft,
    )


def _with_provenance(
    citation: ChatCitationResponse,
    provenance: Any | None,
) -> ChatCitationResponse:
    if provenance is None:
        return citation

    return ChatCitationResponse(
        citation_id=citation.citation_id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=provenance.provider_key,
        source_provider_label=provenance.provider_label,
        source_title=provenance.source_title,
        source_key=provenance.source_key,
        source_section=provenance.source_section,
        source_deep_link=provenance.source_deep_link,
        source_last_synced_at=provenance.source_last_synced_at,
        source_trust_status=cast(Any, provenance.source_trust_status),
        source_acl_snapshot=provenance.source_acl_snapshot,
        conflict_status=citation.conflict_status,
    )


def _with_table_metadata(
    citation: ChatCitationResponse,
    table_metadata_map: dict[str, dict],
) -> ChatCitationResponse:
    """Annotate a citation with table structure metadata when available."""
    meta = table_metadata_map.get(citation.chunk_id)
    if not meta:
        return citation
    raw_conf = meta.get("confidence")
    table_conf: float | None = float(raw_conf) if raw_conf is not None else None
    table_low_conf_warn = table_conf is not None and table_conf < _TABLE_CONFIDENCE_LOW_THRESHOLD
    return ChatCitationResponse(
        citation_id=citation.citation_id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=citation.conflict_status,
        doc_trust_status=citation.doc_trust_status,
        doc_version_label=citation.doc_version_label,
        doc_review_date=citation.doc_review_date,
        doc_effective_date=citation.doc_effective_date,
        doc_stale_warning=citation.doc_stale_warning,
        doc_is_excluded_status=citation.doc_is_excluded_status,
        is_table_chunk=True,
        table_caption=meta.get("caption"),
        table_row_count=meta.get("row_count"),
        table_col_count=meta.get("col_count"),
        table_headers=list(meta.get("headers") or []),
        table_section_context=meta.get("section_context"),
        table_extraction_confidence=table_conf,
        table_low_confidence_warning=table_low_conf_warn,
    )


def _with_ocr_quality(
    citation: ChatCitationResponse,
    ocr_quality_map: dict[str, str],
) -> ChatCitationResponse:
    """Annotate a citation with OCR quality status and low-confidence warning."""
    quality_status = ocr_quality_map.get(citation.document_id)
    if quality_status is None:
        return citation
    return ChatCitationResponse(
        citation_id=citation.citation_id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=citation.conflict_status,
        doc_trust_status=citation.doc_trust_status,
        doc_review_status=citation.doc_review_status,
        doc_review_owner_id=citation.doc_review_owner_id,
        doc_review_due_date=citation.doc_review_due_date,
        doc_expiry_date=citation.doc_expiry_date,
        doc_version_label=citation.doc_version_label,
        doc_review_date=citation.doc_review_date,
        doc_effective_date=citation.doc_effective_date,
        doc_stale_warning=citation.doc_stale_warning,
        doc_expired_warning=citation.doc_expired_warning,
        doc_is_excluded_status=citation.doc_is_excluded_status,
        freshness_state=citation.freshness_state,
        doc_last_updated_at=citation.doc_last_updated_at,
        doc_unreviewed_warning=citation.doc_unreviewed_warning,
        doc_deprecated_warning=citation.doc_deprecated_warning,
        is_table_chunk=citation.is_table_chunk,
        table_caption=citation.table_caption,
        table_row_count=citation.table_row_count,
        table_col_count=citation.table_col_count,
        table_headers=citation.table_headers,
        table_section_context=citation.table_section_context,
        table_extraction_confidence=citation.table_extraction_confidence,
        table_low_confidence_warning=citation.table_low_confidence_warning,
        doc_ocr_quality_status=quality_status,
        doc_ocr_low_confidence_warning=_ocr_quality_service.is_low_confidence(quality_status),
        doc_extraction_quality=citation.doc_extraction_quality,
        doc_extraction_warning=citation.doc_extraction_warning,
        doc_processing_warning=citation.doc_processing_warning,
    )


def _with_conflict_status(
    citation: ChatCitationResponse,
    conflict_result: ConflictDetectionResult,
) -> ChatCitationResponse:
    if not conflict_result.applied or not conflict_result.conflict_detected:
        return citation

    status: Literal["preferred", "conflicting", "neutral"] = "neutral"
    if citation.document_id in conflict_result.preferred_document_ids:
        status = "preferred"
    elif citation.document_id in conflict_result.conflicting_document_ids:
        status = "conflicting"

    return ChatCitationResponse(
        citation_id=citation.citation_id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=status,
        doc_trust_status=citation.doc_trust_status,
        doc_review_status=citation.doc_review_status,
        doc_review_owner_id=citation.doc_review_owner_id,
        doc_review_due_date=citation.doc_review_due_date,
        doc_expiry_date=citation.doc_expiry_date,
        doc_version_label=citation.doc_version_label,
        doc_review_date=citation.doc_review_date,
        doc_effective_date=citation.doc_effective_date,
        doc_stale_warning=citation.doc_stale_warning,
        doc_expired_warning=citation.doc_expired_warning,
        doc_is_excluded_status=citation.doc_is_excluded_status,
        freshness_state=citation.freshness_state,
        doc_last_updated_at=citation.doc_last_updated_at,
        doc_unreviewed_warning=citation.doc_unreviewed_warning,
        doc_deprecated_warning=citation.doc_deprecated_warning,
        is_table_chunk=citation.is_table_chunk,
        table_caption=citation.table_caption,
        table_row_count=citation.table_row_count,
        table_col_count=citation.table_col_count,
        table_headers=citation.table_headers,
        table_section_context=citation.table_section_context,
        table_extraction_confidence=citation.table_extraction_confidence,
        table_low_confidence_warning=citation.table_low_confidence_warning,
        doc_ocr_quality_status=citation.doc_ocr_quality_status,
        doc_ocr_low_confidence_warning=citation.doc_ocr_low_confidence_warning,
        doc_extraction_quality=citation.doc_extraction_quality,
        doc_extraction_warning=citation.doc_extraction_warning,
        doc_processing_warning=citation.doc_processing_warning,
    )


def _with_extraction_quality(
    citation: ChatCitationResponse,
    extraction_quality_map: dict[str, tuple[str | None, float | None, str]],
) -> ChatCitationResponse:
    """Annotate a citation with document extraction quality and processing status (F315).

    extraction_quality_map maps document_id to (document_profile, extraction_confidence, doc_status).
    Sets doc_extraction_quality, doc_extraction_warning, and doc_processing_warning.
    """
    entry = extraction_quality_map.get(citation.document_id)
    if entry is None:
        return citation
    doc_profile, extraction_conf, doc_status = entry
    is_bad_profile = doc_profile in _EXTRACTION_WARNING_PROFILES
    is_low_conf = (
        extraction_conf is not None and extraction_conf < _EXTRACTION_CONFIDENCE_WARN_THRESHOLD
    )
    extraction_warning = is_bad_profile or is_low_conf
    processing_warning = doc_status in _PROCESSING_INCOMPLETE_STATUSES
    return ChatCitationResponse(
        citation_id=citation.citation_id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=citation.conflict_status,
        doc_trust_status=citation.doc_trust_status,
        doc_review_status=citation.doc_review_status,
        doc_review_owner_id=citation.doc_review_owner_id,
        doc_review_due_date=citation.doc_review_due_date,
        doc_expiry_date=citation.doc_expiry_date,
        doc_version_label=citation.doc_version_label,
        doc_review_date=citation.doc_review_date,
        doc_effective_date=citation.doc_effective_date,
        doc_stale_warning=citation.doc_stale_warning,
        doc_expired_warning=citation.doc_expired_warning,
        doc_is_excluded_status=citation.doc_is_excluded_status,
        freshness_state=citation.freshness_state,
        doc_last_updated_at=citation.doc_last_updated_at,
        doc_unreviewed_warning=citation.doc_unreviewed_warning,
        doc_deprecated_warning=citation.doc_deprecated_warning,
        is_table_chunk=citation.is_table_chunk,
        table_caption=citation.table_caption,
        table_row_count=citation.table_row_count,
        table_col_count=citation.table_col_count,
        table_headers=citation.table_headers,
        table_section_context=citation.table_section_context,
        table_extraction_confidence=citation.table_extraction_confidence,
        table_low_confidence_warning=citation.table_low_confidence_warning,
        doc_ocr_quality_status=citation.doc_ocr_quality_status,
        doc_ocr_low_confidence_warning=citation.doc_ocr_low_confidence_warning,
        doc_extraction_quality=doc_profile,
        doc_extraction_warning=extraction_warning,
        doc_processing_warning=processing_warning,
    )


def _build_conflict_context(conflict_result: ConflictDetectionResult) -> str:
    if not conflict_result.applied or conflict_result.agreement_level == "full":
        return ""

    preferred = ", ".join(conflict_result.preferred_document_ids) or "<none>"
    conflicting = ", ".join(conflict_result.conflicting_document_ids) or "<none>"
    pair_lines = [
        f"- {pair.document_id_a} vs {pair.document_id_b}: {pair.topic} ({pair.severity})"
        for pair in conflict_result.conflict_pairs[:5]
    ]
    pair_block = "\n".join(pair_lines) if pair_lines else "- No valid conflict pairs returned."
    return (
        "Source agreement guidance:\n"
        f"- agreement_level: {conflict_result.agreement_level}\n"
        f"- conflict_summary: {conflict_result.conflict_summary or 'Conflicting sources detected.'}\n"
        f"- preferred_document_ids: {preferred}\n"
        f"- conflicting_document_ids: {conflicting}\n"
        f"- conflict_pairs:\n{pair_block}\n"
        "Use the preferred sources as the primary basis, mention disagreements clearly, "
        "and avoid presenting a single certain answer when the sources do not agree.\n"
    )
