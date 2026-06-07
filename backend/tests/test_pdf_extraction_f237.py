"""Unit and integration tests for the F237 PDF extraction pipeline."""

from __future__ import annotations

import io
import struct
import zlib

import pytest

from app.domains.documents.extraction.models import (
    DocumentProfile,
    ExtractionResult,
    ImageBlock,
    PageExtractionResult,
    TableBlock,
    TableCell,
    TextBlock,
)
from app.domains.documents.extraction.pdf_classifier import classify_document_profile
from app.domains.documents.extraction.extraction_service import extract_document


# ---------------------------------------------------------------------------
# Minimal PDF builder helpers
# ---------------------------------------------------------------------------


def _make_minimal_pdf(pages: list[str]) -> bytes:
    """Build a minimal valid multi-page PDF with one text block per page."""
    objects: list[bytes] = []
    offsets: list[int] = []

    def add_obj(content: bytes) -> int:
        obj_id = len(objects) + 1
        objects.append(content)
        return obj_id

    # Build page content streams
    page_obj_ids: list[int] = []
    content_obj_ids: list[int] = []
    for text in pages:
        escaped = text.replace("(", r"\(").replace(")", r"\)")
        stream_data = f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode()
        compressed = zlib.compress(stream_data)
        content = (
            f"<< /Filter /FlateDecode /Length {len(compressed)} >>\nstream\n".encode()
            + compressed
            + b"\nendstream"
        )
        content_id = add_obj(content)
        content_obj_ids.append(content_id)

    for content_id in content_obj_ids:
        page_content = (
            f"<< /Type /Page /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>"
        ).encode()
        page_id = add_obj(page_content)
        page_obj_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    pages_obj = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_obj_ids)} >>".encode()
    pages_id = add_obj(pages_obj)

    catalog = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
    catalog_id = add_obj(catalog)

    # Build xref
    output = b"%PDF-1.4\n"
    object_offsets: list[int] = []
    for i, obj_bytes in enumerate(objects):
        object_offsets.append(len(output))
        output += f"{i + 1} 0 obj\n".encode() + obj_bytes + b"\nendobj\n"

    xref_offset = len(output)
    output += b"xref\n"
    output += f"0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for off in object_offsets:
        output += f"{off:010d} 00000 n \n".encode()

    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return output


def _make_empty_page_pdf() -> bytes:
    """A PDF whose page has no text content stream."""
    page = b"<< /Type /Page /MediaBox [0 0 612 792] /Resources << >> >>"
    pages = b"<< /Type /Pages /Kids [2 0 R] /Count 1 >>"
    catalog = b"<< /Type /Catalog /Pages 1 0 R >>"

    output = b"%PDF-1.4\n"
    offsets: list[int] = []

    for obj in [pages, page, catalog]:
        offsets.append(len(output))
        output += f"{len(offsets)} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_offset = len(output)
    output += b"xref\n"
    output += f"0 {len(offsets) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for off in offsets:
        output += f"{off:010d} 00000 n \n".encode()

    output += (
        f"trailer\n<< /Size {len(offsets) + 1} /Root {len(offsets)} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return output


# ---------------------------------------------------------------------------
# DocumentProfile classification
# ---------------------------------------------------------------------------


def _page(
    *,
    page_number: int = 1,
    text_coverage: float = 0.8,
    image_coverage: float = 0.0,
    char_count: int = 500,
    table_count: int = 0,
    image_count: int = 0,
    requires_ocr: bool = False,
) -> PageExtractionResult:
    return PageExtractionResult(
        page_number=page_number,
        text_blocks=[],
        table_blocks=[
            TableBlock(
                page_number=page_number,
                table_index=i,
                row_count=2,
                col_count=2,
                cells=(),
                markdown="",
                json_data=(),
                caption=None,
                confidence=0.9,
                extraction_engine="test",
                bbox=None,
            )
            for i in range(table_count)
        ],
        image_blocks=[
            ImageBlock(
                page_number=page_number,
                block_type="image",
                bbox=None,
                caption=None,
                confidence=0.9,
            )
            for _ in range(image_count)
        ],
        char_count=char_count,
        page_width=612.0,
        page_height=792.0,
        text_coverage_ratio=text_coverage,
        image_coverage_ratio=image_coverage,
        requires_ocr=requires_ocr,
    )


class TestDocumentProfileClassification:
    def test_text_based(self) -> None:
        pages = [_page(text_coverage=0.8) for _ in range(5)]
        assert classify_document_profile(pages) == DocumentProfile.text_based

    def test_scanned_all_empty(self) -> None:
        pages = [_page(text_coverage=0.0, char_count=0, requires_ocr=True) for _ in range(3)]
        assert classify_document_profile(pages) == DocumentProfile.scanned

    def test_mixed_some_scanned(self) -> None:
        pages = [
            _page(text_coverage=0.8),
            _page(text_coverage=0.0, char_count=0, requires_ocr=True),
        ]
        assert classify_document_profile(pages) == DocumentProfile.mixed

    def test_table_heavy(self) -> None:
        pages = [_page(table_count=3) for _ in range(3)]
        assert classify_document_profile(pages) == DocumentProfile.table_heavy

    def test_figure_heavy(self) -> None:
        pages = [_page(image_count=3) for _ in range(3)]
        assert classify_document_profile(pages) == DocumentProfile.figure_heavy

    def test_form_like(self) -> None:
        pages = [_page(char_count=300, table_count=1) for _ in range(3)]
        assert classify_document_profile(pages) == DocumentProfile.form_like

    def test_empty_pages_returns_unsupported(self) -> None:
        assert classify_document_profile([]) == DocumentProfile.unsupported

    def test_single_scanned_page(self) -> None:
        pages = [_page(text_coverage=0.0, char_count=0)]
        assert classify_document_profile(pages) == DocumentProfile.scanned


# ---------------------------------------------------------------------------
# ExtractionResult.to_sections
# ---------------------------------------------------------------------------


class TestExtractionResultToSections:
    def _result_with_text(self, text: str, page_number: int = 1) -> ExtractionResult:
        block = TextBlock(
            page_number=page_number,
            text=text,
            bbox=None,
            block_type="text",
            confidence=1.0,
        )
        page = _page(page_number=page_number, char_count=len(text))
        page.text_blocks = [block]
        return ExtractionResult(
            document_profile=DocumentProfile.text_based,
            page_count=1,
            pages=[page],
            total_text_blocks=1,
            total_table_blocks=0,
            total_image_blocks=0,
            warnings=[],
            extraction_engine="test",
            extraction_confidence=1.0,
            duration_ms=0,
        )

    def test_text_block_included_in_sections(self) -> None:
        result = self._result_with_text("Hello world")
        sections = result.to_sections()
        assert len(sections) == 1
        assert "Hello world" in sections[0].text

    def test_empty_page_produces_empty_section(self) -> None:
        page = _page(char_count=0)
        result = ExtractionResult(
            document_profile=DocumentProfile.scanned,
            page_count=1,
            pages=[page],
            total_text_blocks=0,
            total_table_blocks=0,
            total_image_blocks=0,
            warnings=[],
            extraction_engine="test",
            extraction_confidence=0.0,
            duration_ms=0,
        )
        sections = result.to_sections()
        assert sections[0].char_count == 0

    def test_table_markdown_included(self) -> None:
        table = TableBlock(
            page_number=1,
            table_index=0,
            row_count=2,
            col_count=2,
            cells=(
                TableCell(row=0, col=0, text="A"),
                TableCell(row=0, col=1, text="B"),
                TableCell(row=1, col=0, text="1"),
                TableCell(row=1, col=1, text="2"),
            ),
            markdown="| A | B |\n| --- | --- |\n| 1 | 2 |",
            json_data=(("A", "B"), ("1", "2")),
            caption=None,
            confidence=0.9,
            extraction_engine="test",
            bbox=None,
        )
        page = _page()
        page.table_blocks = [table]
        result = ExtractionResult(
            document_profile=DocumentProfile.table_heavy,
            page_count=1,
            pages=[page],
            total_text_blocks=0,
            total_table_blocks=1,
            total_image_blocks=0,
            warnings=[],
            extraction_engine="test",
            extraction_confidence=1.0,
            duration_ms=0,
        )
        sections = result.to_sections()
        assert "| A | B |" in sections[0].text

    def test_image_block_reference_included(self) -> None:
        img = ImageBlock(
            page_number=1,
            block_type="figure",
            bbox=None,
            caption="Revenue chart",
            confidence=0.9,
        )
        page = _page()
        page.image_blocks = [img]
        result = ExtractionResult(
            document_profile=DocumentProfile.figure_heavy,
            page_count=1,
            pages=[page],
            total_text_blocks=0,
            total_table_blocks=0,
            total_image_blocks=1,
            warnings=[],
            extraction_engine="test",
            extraction_confidence=1.0,
            duration_ms=0,
        )
        sections = result.to_sections()
        assert "Revenue chart" in sections[0].text
        assert "Figure" in sections[0].text


# ---------------------------------------------------------------------------
# ExtractionResult.to_snapshot
# ---------------------------------------------------------------------------


class TestExtractionResultToSnapshot:
    def test_snapshot_keys(self) -> None:
        page = _page()
        result = ExtractionResult(
            document_profile=DocumentProfile.text_based,
            page_count=1,
            pages=[page],
            total_text_blocks=2,
            total_table_blocks=0,
            total_image_blocks=0,
            warnings=["test warning"],
            extraction_engine="pymupdf",
            extraction_confidence=0.95,
            duration_ms=42,
        )
        snap = result.to_snapshot()
        assert snap["document_profile"] == "text_based"
        assert snap["total_text_blocks"] == 2
        assert snap["extraction_engine"] == "pymupdf"
        assert snap["warnings"] == ["test warning"]
        assert len(snap["pages"]) == 1
        assert snap["pages"][0]["page_number"] == 1

    def test_snapshot_no_document_text(self) -> None:
        block = TextBlock(
            page_number=1,
            text="This is private document text",
            bbox=None,
            block_type="text",
        )
        page = _page()
        page.text_blocks = [block]
        result = ExtractionResult(
            document_profile=DocumentProfile.text_based,
            page_count=1,
            pages=[page],
            total_text_blocks=1,
            total_table_blocks=0,
            total_image_blocks=0,
            warnings=[],
            extraction_engine="pymupdf",
            extraction_confidence=1.0,
            duration_ms=10,
        )
        snap = result.to_snapshot()
        snap_str = str(snap)
        assert "private document text" not in snap_str


# ---------------------------------------------------------------------------
# extract_document: non-PDF passthrough
# ---------------------------------------------------------------------------


class TestExtractDocumentNonPdf:
    def test_txt_produces_text_based_profile(self) -> None:
        content = b"Hello world, this is a plain text document."
        result = extract_document(content, file_type="txt")
        assert result.document_profile == DocumentProfile.text_based
        assert result.page_count == 1
        assert result.total_table_blocks == 0

    def test_txt_sections_have_text(self) -> None:
        content = b"Some document content here."
        result = extract_document(content, file_type="txt")
        sections = result.to_sections()
        assert len(sections) >= 1
        assert sections[0].char_count > 0

    def test_unsupported_file_type_raises(self) -> None:
        with pytest.raises(ValueError):
            extract_document(b"data", file_type="xyz")


# ---------------------------------------------------------------------------
# extract_document: PDF path (minimal PDFs)
# ---------------------------------------------------------------------------


class TestExtractDocumentPdf:
    def test_text_pdf_extraction(self) -> None:
        pdf = _make_minimal_pdf(["Hello world. This is page one."])
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        assert result.page_count >= 1
        assert not result.is_encrypted
        sections = result.to_sections()
        assert len(sections) >= 1

    def test_multi_page_pdf(self) -> None:
        pdf = _make_minimal_pdf(
            [
                "Page one text content here.",
                "Page two text content here.",
                "Page three text content here.",
            ]
        )
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        assert result.page_count == 3
        sections = result.to_sections()
        assert len(sections) == 3

    def test_empty_page_triggers_ocr_flag(self) -> None:
        pdf = _make_empty_page_pdf()
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=30)
        assert result.page_count >= 1
        assert any(p.requires_ocr for p in result.pages)

    def test_corrupted_bytes_raise(self) -> None:
        with pytest.raises(ValueError, match="malformed"):
            extract_document(b"not a pdf", file_type="pdf")

    def test_snapshot_serializable(self) -> None:
        import json

        pdf = _make_minimal_pdf(["Snapshot serialization test page."])
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        snap = result.to_snapshot()
        json.dumps(snap)

    def test_max_pages_respected(self) -> None:
        pdf = _make_minimal_pdf(["Page " + str(i) for i in range(5)])
        result = extract_document(pdf, file_type="pdf", max_pages=2, min_chars_per_page=5)
        assert len(result.pages) == 2

    def test_table_extraction_disabled(self) -> None:
        pdf = _make_minimal_pdf(["Simple text without tables."])
        result = extract_document(
            pdf, file_type="pdf", enable_table_extraction=False, min_chars_per_page=5
        )
        assert result.total_table_blocks == 0

    def test_image_extraction_disabled(self) -> None:
        pdf = _make_minimal_pdf(["Simple text without images."])
        result = extract_document(
            pdf, file_type="pdf", enable_image_extraction=False, min_chars_per_page=5
        )
        assert result.total_image_blocks == 0

    def test_extraction_confidence_range(self) -> None:
        pdf = _make_minimal_pdf(["Confidence test page content."])
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        assert 0.0 <= result.extraction_confidence <= 1.0

    def test_duration_ms_positive(self) -> None:
        pdf = _make_minimal_pdf(["Duration measurement test."])
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# Regression: multilingual text PDFs
# ---------------------------------------------------------------------------


class TestMultilingualTextExtraction:
    @pytest.mark.parametrize(
        "language_text",
        [
            "The quick brown fox jumps over the lazy dog",
            "Der schnelle braune Fuchs springt über den faulen Hund",
            "El rápido zorro marrón salta sobre el perro perezoso",
            "Le renard brun rapide saute par-dessus le chien paresseux",
        ],
    )
    def test_multilingual_extraction_produces_text(self, language_text: str) -> None:
        pdf = _make_minimal_pdf([language_text])
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        sections = result.to_sections()
        assert sections[0].char_count > 0

    def test_multilingual_snapshot_valid(self) -> None:
        pdf = _make_minimal_pdf(["Deutschsprachiger Text für die Extraktion"])
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        snap = result.to_snapshot()
        assert snap["document_profile"] in [p.value for p in DocumentProfile]


# ---------------------------------------------------------------------------
# Security: extraction snapshot must not contain document text
# ---------------------------------------------------------------------------


class TestExtractionSnapshotSecurity:
    def test_snapshot_redacts_text_content(self) -> None:
        pdf = _make_minimal_pdf(["Top secret confidential document content."])
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        snap = result.to_snapshot()
        snap_str = str(snap)
        assert "Top secret confidential" not in snap_str

    def test_warnings_dont_include_text(self) -> None:
        pdf = _make_minimal_pdf(["Normal text page."])
        result = extract_document(pdf, file_type="pdf", min_chars_per_page=5)
        for warning in result.warnings:
            assert "Normal text page" not in warning
