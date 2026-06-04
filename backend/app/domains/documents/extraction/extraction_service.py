from __future__ import annotations

import time

from app.domains.documents.extraction.models import (
    DocumentProfile,
    ExtractionResult,
    PageExtractionResult,
    TextBlock,
)
from app.domains.documents.extraction.pdf_engine import extract_pdf
from app.domains.documents.services.text_extraction import ExtractedSection, extract_text_sections


def extract_document(
    content: bytes,
    *,
    file_type: str,
    min_chars_per_page: int = 30,
    max_pages: int | None = None,
    enable_table_extraction: bool = True,
    enable_image_extraction: bool = True,
) -> ExtractionResult:
    """Route document extraction by file type.

    PDFs use the structured PDF engine. Other types use the legacy extractor wrapped
    in a minimal ExtractionResult so the pipeline stays uniform.
    """
    normalized = file_type.strip().lower()

    if normalized == "pdf":
        return extract_pdf(
            content,
            min_chars_per_page=min_chars_per_page,
            max_pages=max_pages,
            enable_table_extraction=enable_table_extraction,
            enable_image_extraction=enable_image_extraction,
        )

    return _wrap_legacy_extraction(
        content, file_type=normalized, min_chars_per_page=min_chars_per_page
    )


def _wrap_legacy_extraction(
    content: bytes,
    *,
    file_type: str,
    min_chars_per_page: int,
) -> ExtractionResult:
    """Wrap existing text extraction for non-PDF types as a passthrough ExtractionResult."""
    started = time.monotonic()
    try:
        sections = extract_text_sections(file_type=file_type, content=content)
    except ValueError:
        raise

    duration_ms = int((time.monotonic() - started) * 1000)

    pages: list[PageExtractionResult] = []
    for section in sections:
        block = TextBlock(
            page_number=section.page_number,
            text=section.text,
            bbox=None,
            block_type="text",
            confidence=1.0,
        )
        has_text = section.char_count >= min_chars_per_page
        page = PageExtractionResult(
            page_number=section.page_number,
            text_blocks=[block] if section.text else [],
            table_blocks=[],
            image_blocks=[],
            char_count=section.char_count,
            page_width=0.0,
            page_height=0.0,
            text_coverage_ratio=1.0 if has_text else 0.0,
            image_coverage_ratio=0.0,
            requires_ocr=not has_text,
        )
        pages.append(page)

    return ExtractionResult(
        document_profile=DocumentProfile.text_based,
        page_count=len(sections),
        pages=pages,
        total_text_blocks=sum(len(p.text_blocks) for p in pages),
        total_table_blocks=0,
        total_image_blocks=0,
        warnings=[],
        extraction_engine=f"legacy_{file_type}",
        extraction_confidence=1.0,
        duration_ms=duration_ms,
    )
