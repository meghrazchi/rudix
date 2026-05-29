from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.domains.documents.services.text_extraction import ExtractedSection


@dataclass
class OcrDetectionResult:
    requires_ocr: bool
    mode: Literal["text", "scanned", "mixed", "unknown"]
    page_count: int
    native_text_pages: int
    ocr_candidate_pages: list[int] = field(default_factory=list)
    reason: str = ""


def detect_ocr_need(
    sections: list[ExtractedSection],
    *,
    min_chars_per_page: int = 30,
) -> OcrDetectionResult:
    if not sections:
        return OcrDetectionResult(
            requires_ocr=False,
            mode="unknown",
            page_count=0,
            native_text_pages=0,
            reason="no pages to evaluate",
        )

    page_count = len(sections)
    ocr_candidates = [s.page_number for s in sections if s.char_count < min_chars_per_page]
    native_text_pages = page_count - len(ocr_candidates)

    if not ocr_candidates:
        return OcrDetectionResult(
            requires_ocr=False,
            mode="text",
            page_count=page_count,
            native_text_pages=native_text_pages,
            reason="all pages have sufficient native text",
        )

    if native_text_pages == 0:
        return OcrDetectionResult(
            requires_ocr=True,
            mode="scanned",
            page_count=page_count,
            native_text_pages=0,
            ocr_candidate_pages=ocr_candidates,
            reason="no pages have extractable text",
        )

    return OcrDetectionResult(
        requires_ocr=True,
        mode="mixed",
        page_count=page_count,
        native_text_pages=native_text_pages,
        ocr_candidate_pages=ocr_candidates,
        reason=f"{len(ocr_candidates)} of {page_count} pages require OCR",
    )
