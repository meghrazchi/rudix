"""Adaptive hybrid strategy selector.

Analyses heuristic signals derived from extracted document pages and returns
the most appropriate chunking strategy name together with machine-readable
reason codes that can be stored in processing metadata for debugging.

Selection is fully deterministic: the same signals and configuration always
produce the same result.  Reason codes are safe to log (they contain no raw
document text).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domains.documents.chunking.protocol import PageLike

# ---------------------------------------------------------------------------
# Thresholds (module-level constants — configurable via subclassing or tests)
# ---------------------------------------------------------------------------

_HEADING_DENSITY_STRUCTURED: float = 0.5   # headings-per-page ≥ threshold → structured
_SHORT_DOCUMENT_TOKENS: int = 500           # total tokens < threshold → short document
_PDF_MULTI_PAGE_THRESHOLD: int = 1          # page_count > threshold → use page_aware


# ---------------------------------------------------------------------------
# Heuristic signal container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentSignals:
    """All heuristic inputs used by AdaptiveHybridSelector.

    Fields are intentionally named after human-understandable concepts so that
    they can be stored verbatim in processing metadata without exposing raw
    document text.
    """

    file_type: str                          # "pdf" | "docx" | "txt" | "md"
    page_count: int                         # number of extracted pages
    total_token_count: int                  # total tokens across all pages
    ocr_applied: bool = False               # True if OCR was run on at least one page
    avg_chars_per_page: float = 0.0        # text density
    heading_density: float = 0.0           # headings per page (computed from blocks)
    avg_paragraph_tokens: float = 0.0      # average paragraph length in tokens
    language: str | None = None             # ISO 639-1 code


# ---------------------------------------------------------------------------
# Selection result
# ---------------------------------------------------------------------------


@dataclass
class SelectionResult:
    """Output of AdaptiveHybridSelector.select().

    reason_codes is a list of short snake_case tokens that explain *why* the
    strategy was chosen.  They are safe to include in logs and metadata.
    """

    strategy: str                    # e.g. "page_aware"
    reason_codes: list[str] = field(default_factory=list)   # e.g. ["pdf_ocr_applied"]
    signals: DocumentSignals | None = None   # the signals that drove the decision


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------


def compute_document_signals(
    pages: Sequence[PageLike],
    *,
    file_type: str,
    ocr_applied: bool = False,
    language: str | None = None,
    encoding: Any,  # tiktoken Encoding — passed in by caller to avoid re-init cost
) -> DocumentSignals:
    """Derive heuristic signals by scanning page text.

    The function parses each page into typed blocks (heading, paragraph, …) using
    the same parser as HeadingAwareStrategy so the density metrics are consistent
    with what that strategy would do.

    Raw page text is never stored or returned.
    """
    from app.domains.documents.chunking.strategies.blocks import (
        BLOCK_HEADING,
        BLOCK_PARAGRAPH,
        parse_blocks,
    )

    page_count = len(pages)
    if page_count == 0:
        return DocumentSignals(
            file_type=file_type,
            page_count=0,
            total_token_count=0,
            ocr_applied=ocr_applied,
            language=language,
        )

    total_chars = sum(len(p.text) for p in pages)
    avg_chars_per_page = total_chars / page_count

    total_headings = 0
    total_paragraph_tokens = 0
    paragraph_count = 0
    total_token_count = 0

    for page in pages:
        text = page.text
        if not text:
            continue
        tokens = encoding.encode(text)
        total_token_count += len(tokens)

        blocks = parse_blocks(page.page_number, text)
        for block in blocks:
            if block.block_type == BLOCK_HEADING:
                total_headings += 1
            elif block.block_type == BLOCK_PARAGRAPH and block.text.strip():
                block_tokens = encoding.encode(block.text)
                total_paragraph_tokens += len(block_tokens)
                paragraph_count += 1

    heading_density = total_headings / max(1, page_count)
    avg_paragraph_tokens = total_paragraph_tokens / max(1, paragraph_count)

    return DocumentSignals(
        file_type=file_type,
        page_count=page_count,
        total_token_count=total_token_count,
        ocr_applied=ocr_applied,
        avg_chars_per_page=avg_chars_per_page,
        heading_density=heading_density,
        avg_paragraph_tokens=avg_paragraph_tokens,
        language=language,
    )


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------


class AdaptiveHybridSelector:
    """Deterministic, heuristics-driven strategy selector.

    Priority order (first match wins):
        1. force_strategy override  →  whatever is specified
        2. OCR-applied PDF          →  page_aware   (citation provenance)
        3. Multi-page PDF           →  page_aware   (evidence documents)
        4. Single-page PDF + headings → heading_aware
        5. DOCX / Markdown          →  heading_aware (section structure)
        6. Any file with dense headings → heading_aware
        7. Short document           →  paragraph_recursive
        8. Fallback                 →  token_recursive
    """

    HEADING_DENSITY_STRUCTURED: float = _HEADING_DENSITY_STRUCTURED
    SHORT_DOCUMENT_TOKENS: int = _SHORT_DOCUMENT_TOKENS

    @classmethod
    def select(
        cls,
        signals: DocumentSignals,
        *,
        force_strategy: str | None = None,
    ) -> SelectionResult:
        """Return the best strategy for *signals*, with explainable reason codes."""

        # 1. Admin / experiment override — bypasses all heuristics
        if force_strategy:
            return SelectionResult(
                strategy=force_strategy,
                reason_codes=["force_override"],
                signals=signals,
            )

        ft = signals.file_type.lower()

        # 2. OCR PDF — page provenance is critical for citation accuracy
        if ft == "pdf" and signals.ocr_applied:
            return SelectionResult(
                strategy="page_aware",
                reason_codes=["pdf_ocr_applied"],
                signals=signals,
            )

        # 3. Multi-page PDF — preserve page boundaries for evidence documents
        if ft == "pdf" and signals.page_count > _PDF_MULTI_PAGE_THRESHOLD:
            return SelectionResult(
                strategy="page_aware",
                reason_codes=["pdf_multi_page"],
                signals=signals,
            )

        # 4. Single-page PDF with heading structure → heading_aware
        if ft == "pdf" and signals.heading_density >= cls.HEADING_DENSITY_STRUCTURED:
            return SelectionResult(
                strategy="heading_aware",
                reason_codes=["pdf_structured"],
                signals=signals,
            )

        # 5. DOCX / Markdown — always prefer heading_aware regardless of density
        if ft in {"docx", "md"}:
            reason = (
                "docx_md_structured"
                if signals.heading_density >= cls.HEADING_DENSITY_STRUCTURED
                else "docx_md_file_type"
            )
            return SelectionResult(
                strategy="heading_aware",
                reason_codes=[reason],
                signals=signals,
            )

        # 6. Any file type with dense headings → heading_aware
        if signals.heading_density >= cls.HEADING_DENSITY_STRUCTURED:
            return SelectionResult(
                strategy="heading_aware",
                reason_codes=["high_heading_density"],
                signals=signals,
            )

        # 7. Short document (FAQ, policy snippet, knowledge article)
        if signals.total_token_count < cls.SHORT_DOCUMENT_TOKENS:
            return SelectionResult(
                strategy="paragraph_recursive",
                reason_codes=["short_document"],
                signals=signals,
            )

        # 8. Fallback — low confidence in structure, use safe default
        return SelectionResult(
            strategy="token_recursive",
            reason_codes=["fallback_low_confidence"],
            signals=signals,
        )
