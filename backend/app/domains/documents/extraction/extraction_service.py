from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Protocol

from app.domains.documents.extraction.models import (
    DocumentProfile,
    ExtractionResult,
    PageExtractionResult,
    PageSummary,
    TextBlock,
)
from app.domains.documents.extraction.pdf_engine import PdfExtractionStream
from app.domains.documents.services.text_extraction import (
    DocumentSource,
    ExtractedSection,
    iter_text_sections,
)


class ExtractionStream(Protocol):
    """Pages one at a time, then the document-level result (R06-02).

    ``early_profile`` is a profile known before any page is read (``encrypted``);
    ``result()`` is valid once ``pages()`` is exhausted and keeps no page content.
    """

    @property
    def early_profile(self) -> DocumentProfile | None: ...

    def pages(self) -> Iterator[PageExtractionResult]: ...

    def result(self) -> ExtractionResult: ...

    def close(self) -> None: ...


def _legacy_page(section: ExtractedSection, *, min_chars_per_page: int) -> PageExtractionResult:
    block = TextBlock(
        page_number=section.page_number,
        text=section.text,
        bbox=None,
        block_type="text",
        confidence=1.0,
    )
    has_text = section.char_count >= min_chars_per_page
    return PageExtractionResult(
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


class LegacyExtractionStream:
    """TXT and DOCX through the legacy extractor, wrapped page by page."""

    def __init__(self, source: DocumentSource, *, file_type: str, min_chars_per_page: int):
        self._source = source
        self._file_type = file_type
        self._min_chars = min_chars_per_page
        self._started = time.monotonic()
        self._summaries: list[PageSummary] = []
        if file_type not in {"pdf", "txt", "docx"}:
            raise ValueError(f"unsupported file type: {file_type}")

    @property
    def early_profile(self) -> DocumentProfile | None:
        return None

    def pages(self) -> Iterator[PageExtractionResult]:
        for section in iter_text_sections(file_type=self._file_type, content=self._source):
            page = _legacy_page(section, min_chars_per_page=self._min_chars)
            self._summaries.append(page.summary())
            yield page

    def result(self) -> ExtractionResult:
        summaries = self._summaries
        return ExtractionResult(
            document_profile=DocumentProfile.text_based,
            page_count=len(summaries),
            pages=[],
            total_text_blocks=sum(p.text_block_count for p in summaries),
            total_table_blocks=0,
            total_image_blocks=0,
            warnings=[],
            extraction_engine=f"legacy_{self._file_type}",
            extraction_confidence=1.0,
            duration_ms=int((time.monotonic() - self._started) * 1000),
            page_summaries=list(summaries),
        )

    def close(self) -> None:
        return None


class ResultExtractionStream:
    """A finished ``ExtractionResult`` seen as a stream (tests and in-memory callers)."""

    def __init__(self, result: ExtractionResult) -> None:
        self._result = result

    @property
    def early_profile(self) -> DocumentProfile | None:
        profile = self._result.document_profile
        if profile in {DocumentProfile.encrypted, DocumentProfile.corrupted}:
            return profile
        return None

    def pages(self) -> Iterator[PageExtractionResult]:
        yield from self._result.pages

    def result(self) -> ExtractionResult:
        return self._result

    def close(self) -> None:
        return None


def stream_document(
    source: DocumentSource,
    *,
    file_type: str,
    min_chars_per_page: int = 30,
    max_pages: int | None = None,
    enable_table_extraction: bool = True,
    enable_image_extraction: bool = True,
) -> ExtractionStream:
    """Open a page-by-page extraction; the caller closes it."""
    normalized = file_type.strip().lower()
    if normalized == "pdf":
        return PdfExtractionStream(
            source,
            min_chars_per_page=min_chars_per_page,
            max_pages=max_pages,
            enable_table_extraction=enable_table_extraction,
            enable_image_extraction=enable_image_extraction,
        )
    return LegacyExtractionStream(
        source, file_type=normalized, min_chars_per_page=min_chars_per_page
    )


def extract_document(
    content: DocumentSource,
    *,
    file_type: str,
    min_chars_per_page: int = 30,
    max_pages: int | None = None,
    enable_table_extraction: bool = True,
    enable_image_extraction: bool = True,
) -> ExtractionResult:
    """Route document extraction by file type and return every page.

    PDFs use the structured PDF engine. Other types use the legacy extractor wrapped
    in a minimal ExtractionResult so the pipeline stays uniform.
    """
    stream = stream_document(
        content,
        file_type=file_type,
        min_chars_per_page=min_chars_per_page,
        max_pages=max_pages,
        enable_table_extraction=enable_table_extraction,
        enable_image_extraction=enable_image_extraction,
    )
    try:
        pages = list(stream.pages())
        result = stream.result()
    finally:
        stream.close()
    if not result.is_encrypted:
        result.pages = pages
        result.page_summaries = None
    return result
