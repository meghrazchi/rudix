from __future__ import annotations

from app.domains.documents.extraction.models import DocumentProfile, PageExtractionResult

_SCANNED_TEXT_COVERAGE_THRESHOLD = 0.05
_MIXED_TEXT_COVERAGE_THRESHOLD = 0.50
_TABLE_HEAVY_RATIO = 1.5
_FIGURE_HEAVY_RATIO = 1.5
_FORM_LIKE_MAX_AVG_CHARS_PER_PAGE = 800


def classify_document_profile(
    pages: list[PageExtractionResult],
    *,
    min_chars_per_page: int = 30,
) -> DocumentProfile:
    if not pages:
        return DocumentProfile.unsupported

    page_count = len(pages)

    scanned_pages = sum(
        1 for p in pages if p.text_coverage_ratio < _SCANNED_TEXT_COVERAGE_THRESHOLD
    )
    total_tables = sum(len(p.table_blocks) for p in pages)
    total_images = sum(len(p.image_blocks) for p in pages)
    total_chars = sum(p.char_count for p in pages)

    if scanned_pages == page_count:
        return DocumentProfile.scanned

    if scanned_pages > 0:
        return DocumentProfile.mixed

    tables_per_page = total_tables / page_count
    images_per_page = total_images / page_count
    avg_chars_per_page = total_chars / page_count

    if tables_per_page >= _TABLE_HEAVY_RATIO:
        return DocumentProfile.table_heavy

    if images_per_page >= _FIGURE_HEAVY_RATIO:
        return DocumentProfile.figure_heavy

    if avg_chars_per_page <= _FORM_LIKE_MAX_AVG_CHARS_PER_PAGE and total_tables > 0:
        return DocumentProfile.form_like

    return DocumentProfile.text_based
