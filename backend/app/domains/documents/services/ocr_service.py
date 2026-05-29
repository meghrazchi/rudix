from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import fitz

if TYPE_CHECKING:
    from app.domains.documents.services.text_extraction import ExtractedSection


@dataclass
class OcrPageResult:
    page_number: int
    text: str
    languages: list[str]
    status: Literal["completed", "failed", "skipped"]
    warning: str | None = None


@dataclass
class OcrDocumentResult:
    status: Literal["completed", "partial", "failed", "skipped"]
    pages: list[OcrPageResult]
    duration_ms: int
    languages: list[str]
    mode: str = ""


def run_ocr(
    content: bytes,
    candidate_pages: list[int],
    *,
    languages: str = "eng",
    dpi: int = 300,
    page_timeout_seconds: int = 60,
    max_pages: int = 100,
) -> OcrDocumentResult:
    """Run OCR using PyMuPDF's built-in Tesseract integration.

    Calls Tesseract's C API directly (no subprocess) so it works safely inside
    Celery's forked daemon worker processes on macOS and Linux.
    """
    started_at = time.monotonic()
    lang_list = [lang.strip() for lang in languages.split(",") if lang.strip()]
    lang_str = "+".join(lang_list)
    limited_pages = candidate_pages[:max_pages]

    if not limited_pages:
        return OcrDocumentResult(
            status="skipped",
            pages=[],
            duration_ms=0,
            languages=lang_list,
        )

    ocr_pages: list[OcrPageResult] = []
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        return OcrDocumentResult(
            status="failed",
            pages=[
                OcrPageResult(
                    page_number=p,
                    text="",
                    languages=lang_list,
                    status="failed",
                    warning=f"PDF open failed: {exc}",
                )
                for p in limited_pages
            ],
            duration_ms=duration_ms,
            languages=lang_list,
        )

    try:
        for page_number in limited_pages:
            try:
                page = doc[page_number - 1]
                textpage = page.get_textpage_ocr(language=lang_str, dpi=dpi, full=True)
                text = page.get_text(textpage=textpage).strip()
                ocr_pages.append(
                    OcrPageResult(
                        page_number=page_number,
                        text=text,
                        languages=lang_list,
                        status="completed",
                    )
                )
            except Exception as exc:
                ocr_pages.append(
                    OcrPageResult(
                        page_number=page_number,
                        text="",
                        languages=lang_list,
                        status="failed",
                        warning=f"OCR failed on page {page_number}: {exc}",
                    )
                )
    finally:
        doc.close()

    duration_ms = int((time.monotonic() - started_at) * 1000)
    completed = sum(1 for p in ocr_pages if p.status == "completed")
    failed = sum(1 for p in ocr_pages if p.status == "failed")

    if completed == 0 and failed > 0:
        overall: Literal["completed", "partial", "failed", "skipped"] = "failed"
    elif failed > 0:
        overall = "partial"
    elif completed > 0:
        overall = "completed"
    else:
        overall = "skipped"

    return OcrDocumentResult(
        status=overall,
        pages=ocr_pages,
        duration_ms=duration_ms,
        languages=lang_list,
    )


def merge_ocr_with_sections(
    native_sections: list[ExtractedSection],
    ocr_result: OcrDocumentResult,
    *,
    min_chars_per_page: int = 30,
) -> list[ExtractedSection]:
    from app.domains.documents.services.text_extraction import _coerce_section

    ocr_text_by_page = {
        p.page_number: p.text
        for p in ocr_result.pages
        if p.status == "completed" and p.text
    }

    merged: list[ExtractedSection] = []
    for section in native_sections:
        if section.char_count < min_chars_per_page and section.page_number in ocr_text_by_page:
            merged.append(_coerce_section(section.page_number, ocr_text_by_page[section.page_number]))
        else:
            merged.append(section)
    return merged
