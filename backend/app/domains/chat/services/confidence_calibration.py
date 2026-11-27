"""Confidence signals, calibration multipliers, and evidence-quality inputs (R05-01)."""

from app.core.config import settings
from app.domains.chat.schemas.trust_metadata import (
    EvidenceQualityRecord,
)
from app.domains.chat.services.confidence_service import ConfidenceChunkSignal
from app.domains.chat.services.conflict_detection_service import (
    ConflictDetectionResult,
)
from app.domains.chat.services.retrieved_chunk import RetrievedChunk


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


def _confidence_category_from_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= settings.confidence_high_threshold:
        return "high"
    if score >= settings.confidence_medium_threshold:
        return "medium"
    return "low"


def _compute_freshness_multiplier(stale_count: int, total_count: int) -> float:
    """Map stale-source fraction to a [0.70, 1.0] confidence multiplier."""
    if total_count == 0 or stale_count == 0:
        return 1.0
    stale_fraction = stale_count / total_count
    return max(0.70, 1.0 - stale_fraction * settings.confidence_freshness_stale_penalty)


def _compute_ocr_quality_multiplier(citations: list) -> float:
    """Average OCR-quality multiplier across all citations that carry OCR status."""
    _ocr_map: dict[str, float] = {
        "high": 1.0,
        "not_required": 1.0,
        "medium": settings.confidence_ocr_medium_multiplier,
        "low": settings.confidence_ocr_low_multiplier,
        "failed": settings.confidence_ocr_failed_multiplier,
    }
    multipliers = [
        _ocr_map[q]
        for c in citations
        if (q := getattr(c, "doc_ocr_quality_status", None)) in _ocr_map
    ]
    return round(sum(multipliers) / len(multipliers), 4) if multipliers else 1.0


def _compute_conflict_multiplier(conflict_result: ConflictDetectionResult) -> float:
    """Map conflict agreement_level to a confidence multiplier."""
    level = conflict_result.agreement_level
    if level == "conflicting":
        return max(0.0, 1.0 - settings.confidence_conflict_penalty_conflicting)
    if level == "partial":
        return max(0.0, 1.0 - settings.confidence_conflict_penalty_partial)
    return 1.0


_TABLE_CONFIDENCE_LOW_THRESHOLD = 0.4


_TABLE_CONFIDENCE_VERY_LOW_THRESHOLD = 0.2


_EXTRACTION_CONFIDENCE_WARN_THRESHOLD = 0.5


_EXTRACTION_WARNING_PROFILES = frozenset({"corrupted", "unsupported", "encrypted"})


_PROCESSING_INCOMPLETE_STATUSES = frozenset(
    {"processing", "failed", "extraction_failed", "quarantined", "blocked", "infected"}
)


def _compute_table_quality_multiplier(citations: list) -> float:
    """Average table-extraction quality penalty across table citations (F315).

    Citations that are not table chunks are excluded. A low-confidence table
    (< 0.4) yields a 0.85 multiplier; very low-confidence (< 0.2) yields 0.70.
    """
    multipliers: list[float] = []
    for c in citations:
        if not getattr(c, "is_table_chunk", False):
            continue
        conf = getattr(c, "table_extraction_confidence", None)
        if conf is None:
            continue
        if conf < _TABLE_CONFIDENCE_VERY_LOW_THRESHOLD:
            multipliers.append(0.70)
        elif conf < _TABLE_CONFIDENCE_LOW_THRESHOLD:
            multipliers.append(0.85)
        else:
            multipliers.append(1.0)
    return round(sum(multipliers) / len(multipliers), 4) if multipliers else 1.0


def _compute_extraction_quality_multiplier(citations: list) -> float:
    """Return 0.85 when any citation carries a document extraction warning (F315)."""
    if any(getattr(c, "doc_extraction_warning", False) for c in citations):
        return 0.85
    return 1.0


def _build_evidence_quality_record(citations: list) -> "EvidenceQualityRecord":
    """Build an aggregated evidence quality summary from annotated citations (F315)."""
    table_low_conf_count = sum(
        1 for c in citations if getattr(c, "table_low_confidence_warning", False)
    )
    extraction_warn_count = sum(1 for c in citations if getattr(c, "doc_extraction_warning", False))
    processing_warn_count = sum(1 for c in citations if getattr(c, "doc_processing_warning", False))
    any_incomplete = processing_warn_count > 0

    warning_reasons: list[str] = []
    if table_low_conf_count > 0:
        warning_reasons.append(
            f"{table_low_conf_count} cited table chunk"
            f"{'s have' if table_low_conf_count > 1 else ' has'} low extraction confidence"
            " — table data may be inaccurate."
        )
    if extraction_warn_count > 0:
        warning_reasons.append(
            f"{extraction_warn_count} source document"
            f"{'s have' if extraction_warn_count > 1 else ' has'} poor extraction quality"
            " — text coverage may be incomplete."
        )
    if processing_warn_count > 0:
        warning_reasons.append(
            f"{processing_warn_count} source document"
            f"{'s have' if processing_warn_count > 1 else ' has'} incomplete or failed"
            " processing — content may be missing."
        )

    return EvidenceQualityRecord(
        table_low_confidence_count=table_low_conf_count,
        extraction_warning_count=extraction_warn_count,
        processing_warning_count=processing_warn_count,
        any_incomplete_documents=any_incomplete,
        warning_reasons=warning_reasons,
    )


def _build_evidence_quality_inputs(citations: list) -> dict[str, int]:
    """Extract integer quality signal counts from citations for the critic (F339)."""
    return {
        "table_low_confidence_count": sum(
            1 for c in citations if getattr(c, "table_low_confidence_warning", False)
        ),
        "extraction_warning_count": sum(
            1 for c in citations if getattr(c, "doc_extraction_warning", False)
        ),
    }
