"""Unit and integration tests for F210: adaptive hybrid chunking.

Covers:
  - Selector logic for PDF, OCR PDF, DOCX, Markdown, short TXT, long TXT, and
    mixed-language documents
  - force_strategy override
  - Determinism guarantee
  - compute_document_signals() signal computation
  - AdaptiveHybridStrategy end-to-end delegation
  - Registry registration
  - Fallback safety (never blocks indexing)
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

import tiktoken

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.registry import get_registry
from app.domains.documents.chunking.selector import (
    AdaptiveHybridSelector,
    DocumentSignals,
    compute_document_signals,
)
from app.domains.documents.chunking.strategies.adaptive_hybrid import AdaptiveHybridStrategy
from app.domains.documents.services.text_extraction import ExtractedSection

MODEL = "text-embedding-3-small"
IDX = "v-test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pages(*texts: str) -> list[ExtractedSection]:
    return [
        ExtractedSection(page_number=i + 1, text=t, char_count=len(t)) for i, t in enumerate(texts)
    ]


def _signals(
    *,
    file_type: str = "txt",
    page_count: int = 1,
    total_token_count: int = 1000,
    ocr_applied: bool = False,
    heading_density: float = 0.0,
    language: str | None = None,
) -> DocumentSignals:
    return DocumentSignals(
        file_type=file_type,
        page_count=page_count,
        total_token_count=total_token_count,
        ocr_applied=ocr_applied,
        heading_density=heading_density,
        language=language,
    )


def _encoding():
    return tiktoken.get_encoding("cl100k_base")


def _adaptive(
    file_type: str = "txt",
    ocr_applied: bool = False,
    force_strategy: str | None = None,
    size: int = 100,
    overlap: int = 20,
) -> AdaptiveHybridStrategy:
    opts: dict = {"file_type": file_type, "ocr_applied": ocr_applied}
    if force_strategy:
        opts["force_strategy"] = force_strategy
    profile = ChunkingProfileConfig.model_construct(
        strategy="adaptive_hybrid",
        chunk_size_tokens=size,
        chunk_overlap_tokens=overlap,
        min_tokens=None,
        language=None,
        strategy_options=opts,
    )
    return AdaptiveHybridStrategy(
        profile=profile,
        embedding_model=MODEL,
        index_version=IDX,
    )


# ===========================================================================
# AdaptiveHybridSelector — selection logic
# ===========================================================================


class TestSelectorPDF:
    def test_ocr_pdf_selects_page_aware(self) -> None:
        sig = _signals(file_type="pdf", ocr_applied=True)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "page_aware"
        assert "pdf_ocr_applied" in result.reason_codes

    def test_multi_page_pdf_selects_page_aware(self) -> None:
        sig = _signals(file_type="pdf", page_count=5)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "page_aware"
        assert "pdf_multi_page" in result.reason_codes

    def test_single_page_pdf_with_headings_selects_heading_aware(self) -> None:
        sig = _signals(file_type="pdf", page_count=1, heading_density=1.5)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "heading_aware"
        assert "pdf_structured" in result.reason_codes

    def test_single_page_pdf_no_headings_long_falls_back(self) -> None:
        sig = _signals(file_type="pdf", page_count=1, heading_density=0.0, total_token_count=800)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "token_recursive"
        assert "fallback_low_confidence" in result.reason_codes

    def test_single_page_pdf_no_headings_short_uses_paragraph(self) -> None:
        sig = _signals(file_type="pdf", page_count=1, heading_density=0.0, total_token_count=300)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "paragraph_recursive"
        assert "short_document" in result.reason_codes

    def test_ocr_pdf_wins_over_multi_page_check(self) -> None:
        # Both OCR and multi-page — OCR wins (priority 2 before 3).
        sig = _signals(file_type="pdf", page_count=10, ocr_applied=True)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "page_aware"
        assert "pdf_ocr_applied" in result.reason_codes


class TestSelectorDOCX:
    def test_docx_with_headings_selects_heading_aware(self) -> None:
        sig = _signals(file_type="docx", heading_density=2.0)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "heading_aware"
        assert "docx_md_structured" in result.reason_codes

    def test_docx_without_headings_still_selects_heading_aware(self) -> None:
        sig = _signals(file_type="docx", heading_density=0.0)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "heading_aware"
        assert "docx_md_file_type" in result.reason_codes

    def test_docx_case_insensitive(self) -> None:
        sig = _signals(file_type="DOCX", heading_density=1.0)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "heading_aware"


class TestSelectorMarkdown:
    def test_md_with_headings_selects_heading_aware(self) -> None:
        sig = _signals(file_type="md", heading_density=3.0)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "heading_aware"
        assert "docx_md_structured" in result.reason_codes

    def test_md_without_headings_selects_heading_aware(self) -> None:
        sig = _signals(file_type="md", heading_density=0.0)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "heading_aware"
        assert "docx_md_file_type" in result.reason_codes


class TestSelectorTXT:
    def test_short_txt_selects_paragraph_recursive(self) -> None:
        sig = _signals(file_type="txt", total_token_count=200, heading_density=0.0)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "paragraph_recursive"
        assert "short_document" in result.reason_codes

    def test_long_txt_no_structure_falls_back(self) -> None:
        sig = _signals(file_type="txt", total_token_count=5000, heading_density=0.0)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "token_recursive"
        assert "fallback_low_confidence" in result.reason_codes

    def test_txt_with_dense_headings_selects_heading_aware(self) -> None:
        sig = _signals(file_type="txt", heading_density=2.0, total_token_count=2000)
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "heading_aware"
        assert "high_heading_density" in result.reason_codes

    def test_mixed_language_txt_long_falls_back(self) -> None:
        sig = _signals(
            file_type="txt",
            total_token_count=3000,
            heading_density=0.0,
            language="fr",
        )
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "token_recursive"

    def test_mixed_language_short_uses_paragraph(self) -> None:
        sig = _signals(
            file_type="txt",
            total_token_count=100,
            heading_density=0.0,
            language="ja",
        )
        result = AdaptiveHybridSelector.select(sig)
        assert result.strategy == "paragraph_recursive"


class TestSelectorForceOverride:
    def test_force_strategy_bypasses_all_heuristics(self) -> None:
        # Even a scanned PDF with many pages → forced to token_recursive.
        sig = _signals(file_type="pdf", page_count=50, ocr_applied=True)
        result = AdaptiveHybridSelector.select(sig, force_strategy="token_recursive")
        assert result.strategy == "token_recursive"
        assert result.reason_codes == ["force_override"]

    def test_force_strategy_any_name_passes_through(self) -> None:
        sig = _signals(file_type="txt", total_token_count=10)
        result = AdaptiveHybridSelector.select(sig, force_strategy="sentence_window")
        assert result.strategy == "sentence_window"

    def test_force_strategy_none_does_not_override(self) -> None:
        sig = _signals(file_type="pdf", page_count=5)
        result = AdaptiveHybridSelector.select(sig, force_strategy=None)
        assert result.strategy != "token_recursive" or result.reason_codes != ["force_override"]


class TestSelectorDeterminism:
    def test_same_signals_always_same_result(self) -> None:
        sig = _signals(file_type="pdf", page_count=3, ocr_applied=False)
        results = [AdaptiveHybridSelector.select(sig).strategy for _ in range(10)]
        assert len(set(results)) == 1

    def test_reason_codes_deterministic(self) -> None:
        sig = _signals(file_type="docx", heading_density=1.5)
        codes = [AdaptiveHybridSelector.select(sig).reason_codes for _ in range(5)]
        assert all(c == codes[0] for c in codes)


class TestSelectorResultContainsSignals:
    def test_result_carries_signals(self) -> None:
        sig = _signals(file_type="pdf", page_count=2)
        result = AdaptiveHybridSelector.select(sig)
        assert result.signals is sig


# ===========================================================================
# compute_document_signals
# ===========================================================================


class TestComputeDocumentSignals:
    def test_empty_pages_returns_zero_counts(self) -> None:
        enc = _encoding()
        signals = compute_document_signals([], file_type="pdf", ocr_applied=False, encoding=enc)
        assert signals.page_count == 0
        assert signals.total_token_count == 0
        assert signals.heading_density == 0.0

    def test_page_count_matches_input(self) -> None:
        enc = _encoding()
        pages = _pages("Hello world.", "Second page content.")
        sig = compute_document_signals(pages, file_type="txt", encoding=enc)
        assert sig.page_count == 2

    def test_heading_density_detected_from_markdown(self) -> None:
        enc = _encoding()
        text = "# Title\n\nSome content.\n\n## Sub-heading\n\nMore content."
        pages = _pages(text)
        sig = compute_document_signals(pages, file_type="md", encoding=enc)
        assert sig.heading_density >= 1.0  # at least 1 heading per page

    def test_ocr_applied_flag_preserved(self) -> None:
        enc = _encoding()
        pages = _pages("Some text.")
        sig = compute_document_signals(pages, file_type="pdf", ocr_applied=True, encoding=enc)
        assert sig.ocr_applied is True

    def test_language_preserved(self) -> None:
        enc = _encoding()
        pages = _pages("Bonjour le monde.")
        sig = compute_document_signals(pages, file_type="txt", language="fr", encoding=enc)
        assert sig.language == "fr"

    def test_total_tokens_positive_for_nonempty_text(self) -> None:
        enc = _encoding()
        pages = _pages(" ".join(f"word{i}" for i in range(50)))
        sig = compute_document_signals(pages, file_type="txt", encoding=enc)
        assert sig.total_token_count > 0

    def test_avg_chars_per_page_computed(self) -> None:
        enc = _encoding()
        pages = _pages("Hello.", "World.")
        sig = compute_document_signals(pages, file_type="txt", encoding=enc)
        assert sig.avg_chars_per_page > 0

    def test_no_headings_in_plain_text(self) -> None:
        enc = _encoding()
        pages = _pages("Just a plain paragraph. No structure here. Nothing special.")
        sig = compute_document_signals(pages, file_type="txt", encoding=enc)
        assert sig.heading_density == 0.0

    def test_multilingual_text_no_crash(self) -> None:
        enc = _encoding()
        pages = _pages("Hello world. 你好世界。مرحبا بالعالم.")
        sig = compute_document_signals(pages, file_type="txt", encoding=enc)
        assert sig.total_token_count > 0


# ===========================================================================
# AdaptiveHybridStrategy — end-to-end delegation
# ===========================================================================


class TestAdaptiveHybridStrategy:
    @pytest.mark.asyncio
    async def test_pdf_ocr_delegates_to_page_aware(self) -> None:
        strat = _adaptive(file_type="pdf", ocr_applied=True)
        long_text = " ".join(f"word{i}" for i in range(50))
        pages = _pages(long_text, " ".join(f"page2w{i}" for i in range(50)))
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks
        assert strat.last_selection is not None
        assert strat.last_selection.strategy == "page_aware"
        assert all(c.strategy_name == "page_aware" for c in chunks)

    @pytest.mark.asyncio
    async def test_multi_page_pdf_delegates_to_page_aware(self) -> None:
        strat = _adaptive(file_type="pdf")
        pages = _pages(
            "Content on page one.",
            "Content on page two.",
            "Content on page three.",
        )
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks
        assert strat.last_selection is not None
        assert strat.last_selection.strategy == "page_aware"

    @pytest.mark.asyncio
    async def test_docx_delegates_to_heading_aware(self) -> None:
        strat = _adaptive(file_type="docx")
        text = "# Introduction\n\nThis is the intro.\n\n# Conclusion\n\nThis is the end."
        pages = _pages(text)
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks
        assert strat.last_selection is not None
        assert strat.last_selection.strategy == "heading_aware"

    @pytest.mark.asyncio
    async def test_markdown_delegates_to_heading_aware(self) -> None:
        strat = _adaptive(file_type="md")
        text = "# Section\n\nContent here.\n\n## Sub-section\n\nMore content."
        pages = _pages(text)
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks
        assert strat.last_selection is not None
        assert strat.last_selection.strategy == "heading_aware"

    @pytest.mark.asyncio
    async def test_short_txt_delegates_to_paragraph_recursive(self) -> None:
        # ~50 tokens — well below the 500-token threshold.
        strat = _adaptive(file_type="txt")
        text = " ".join(f"word{i}" for i in range(30))
        pages = _pages(text)
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks
        assert strat.last_selection is not None
        assert strat.last_selection.strategy == "paragraph_recursive"

    @pytest.mark.asyncio
    async def test_long_txt_no_structure_falls_back_to_token_recursive(self) -> None:
        strat = _adaptive(file_type="txt", size=50, overlap=10)
        text = " ".join(f"word{i}" for i in range(600))  # >> 500 tokens
        pages = _pages(text)
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks
        assert strat.last_selection is not None
        assert strat.last_selection.strategy == "token_recursive"

    @pytest.mark.asyncio
    async def test_force_strategy_overrides_selection(self) -> None:
        # Multi-page PDF would normally go to page_aware — override to heading_aware.
        strat = _adaptive(file_type="pdf", force_strategy="heading_aware")
        pages = _pages(
            "# Title\n\nContent page one.",
            "## Section\n\nContent page two.",
        )
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks
        assert strat.last_selection is not None
        assert strat.last_selection.strategy == "heading_aware"
        assert strat.last_selection.reason_codes == ["force_override"]
        assert all(c.strategy_name == "heading_aware" for c in chunks)

    @pytest.mark.asyncio
    async def test_is_deterministic(self) -> None:
        strat_a = _adaptive(file_type="pdf", ocr_applied=True)
        strat_b = _adaptive(file_type="pdf", ocr_applied=True)
        pages = _pages(" ".join(f"w{i}" for i in range(100)))
        doc_id = uuid4()
        chunks_a = await strat_a.chunk(document_id=doc_id, pages=pages)
        chunks_b = await strat_b.chunk(document_id=doc_id, pages=pages)
        assert [c.text for c in chunks_a] == [c.text for c in chunks_b]

    @pytest.mark.asyncio
    async def test_empty_pages_produces_empty_result(self) -> None:
        strat = _adaptive(file_type="pdf")
        chunks = await strat.chunk(document_id=uuid4(), pages=[])
        assert chunks == []

    @pytest.mark.asyncio
    async def test_last_selection_populated_after_chunk(self) -> None:
        strat = _adaptive(file_type="txt")
        assert strat.last_selection is None
        pages = _pages("Hello world.")
        await strat.chunk(document_id=uuid4(), pages=pages)
        assert strat.last_selection is not None

    @pytest.mark.asyncio
    async def test_fallback_never_raises(self) -> None:
        # Simulate a document with no detectable structure — must not raise.
        strat = _adaptive(file_type="txt", size=60, overlap=10)
        text = " ".join(f"word{i}" for i in range(700))
        pages = _pages(text)
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks  # always produces output

    @pytest.mark.asyncio
    async def test_multilingual_no_crash(self) -> None:
        strat = _adaptive(file_type="txt", size=50, overlap=10)
        text = "Hello world. 你好世界。مرحبا بالعالم. Bonjour le monde."
        pages = _pages(text)
        chunks = await strat.chunk(document_id=uuid4(), pages=pages)
        assert chunks


# ===========================================================================
# Registry
# ===========================================================================


def test_registry_knows_adaptive_hybrid() -> None:
    assert "adaptive_hybrid" in get_registry().known_strategies()


def test_registry_resolves_adaptive_hybrid_to_correct_type() -> None:
    profile = ChunkingProfileConfig.model_construct(
        strategy="adaptive_hybrid",
        chunk_size_tokens=200,
        chunk_overlap_tokens=40,
        min_tokens=None,
        language=None,
        strategy_options={"file_type": "txt"},
    )
    strategy = get_registry().resolve(profile, embedding_model=MODEL, index_version=IDX)
    assert isinstance(strategy, AdaptiveHybridStrategy)


# ===========================================================================
# Backward compatibility — existing strategies still registered
# ===========================================================================


def test_all_baseline_strategies_still_registered() -> None:
    known = get_registry().known_strategies()
    for name in [
        "token_recursive",
        "token_fixed",
        "paragraph_recursive",
        "sentence_window",
        "page_aware",
        "heading_aware",
        "adaptive_hybrid",
    ]:
        assert name in known, f"Strategy {name!r} missing from registry"
