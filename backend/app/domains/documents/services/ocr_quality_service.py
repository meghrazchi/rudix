"""OCR quality scoring and retrieval downranking (F299).

Quality classification thresholds:
  high         avg_confidence >= 0.70  → neutral retrieval weight
  medium       avg_confidence >= 0.40  → slight retrieval penalty
  low          avg_confidence <  0.40  → moderate retrieval penalty
  failed       OCR status is 'failed'  → significant retrieval penalty
  not_required non-OCR file types or docs that didn't need OCR

Retrieval score multipliers penalise low-confidence OCR results so that
high-quality text chunks are preferred over garbled OCR output.
"""

from __future__ import annotations

from app.models.enums import OcrQualityStatus

# ---------------------------------------------------------------------------
# Thresholds and multipliers
# ---------------------------------------------------------------------------

_HIGH_CONFIDENCE_THRESHOLD = 0.70
_MEDIUM_CONFIDENCE_THRESHOLD = 0.40

OCR_QUALITY_SCORE_MULTIPLIERS: dict[str, float] = {
    OcrQualityStatus.high: 1.0,
    OcrQualityStatus.medium: 0.90,
    OcrQualityStatus.low: 0.70,
    OcrQualityStatus.failed: 0.50,
    OcrQualityStatus.not_required: 1.0,
}

# Quality statuses that should surface a warning in chat citations.
LOW_QUALITY_STATUSES: frozenset[str] = frozenset({OcrQualityStatus.low, OcrQualityStatus.failed})


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class OcrQualityService:
    """Classifies OCR quality and provides retrieval score multipliers.

    All methods are synchronous and side-effect free.
    """

    def classify(
        self,
        *,
        avg_confidence: float | None,
        ocr_status: str | None,
        ocr_applied: bool,
        file_type: str,
    ) -> str:
        """Return the OcrQualityStatus string for a processed document.

        Args:
            avg_confidence: mean confidence across completed OCR pages (0–1).
            ocr_status: overall OCR run status ('completed', 'partial', 'failed', 'skipped').
            ocr_applied: True when OCR was actually triggered for this document.
            file_type: document file type ('pdf', 'txt', 'docx').
        """
        if file_type in ("txt", "docx") or not ocr_applied:
            return OcrQualityStatus.not_required

        if ocr_status == "failed":
            return OcrQualityStatus.failed

        if avg_confidence is None:
            return OcrQualityStatus.not_required

        if avg_confidence >= _HIGH_CONFIDENCE_THRESHOLD:
            return OcrQualityStatus.high
        if avg_confidence >= _MEDIUM_CONFIDENCE_THRESHOLD:
            return OcrQualityStatus.medium
        return OcrQualityStatus.low

    def retrieval_score_multiplier(self, quality_status: str) -> float:
        """Return the score multiplier for a given OCR quality status."""
        return OCR_QUALITY_SCORE_MULTIPLIERS.get(quality_status, 1.0)

    def is_low_confidence(self, quality_status: str | None) -> bool:
        """Return True when a citation should surface a low-OCR-quality warning."""
        return quality_status in LOW_QUALITY_STATUSES

    def build_quality_map(self, documents: list[object]) -> dict[str, str]:
        """Build a document_id → ocr_quality_status index from ORM Document objects.

        Documents without an OCR quality status are treated as 'not_required'
        so they receive a neutral score multiplier.
        """
        quality_map: dict[str, str] = {}
        for doc in documents:
            doc_id = str(getattr(doc, "id", None) or "")
            if not doc_id:
                continue
            status = getattr(doc, "ocr_quality_status", None)
            quality_map[doc_id] = status or OcrQualityStatus.not_required
        return quality_map

    def apply_quality_score(
        self,
        score: float,
        document_id: str,
        quality_map: dict[str, str],
    ) -> float:
        """Adjust a retrieval score by the OCR quality multiplier for a document."""
        status = quality_map.get(document_id, OcrQualityStatus.not_required)
        return score * self.retrieval_score_multiplier(status)
