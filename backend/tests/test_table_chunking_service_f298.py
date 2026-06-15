"""Unit tests for TableChunkingService — F298."""

from __future__ import annotations

import os

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

from app.domains.documents.extraction.models import BoundingBox, TableBlock, TableCell
from app.domains.documents.services.table_chunking_service import (
    TableChunkResult,
    build_docx_table_chunk,
    build_table_chunk,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_table(
    *,
    rows: list[list[str]],
    table_index: int = 0,
    page_number: int = 1,
    caption: str | None = None,
    confidence: float = 0.9,
) -> TableBlock:
    cells: list[TableCell] = []
    json_rows: list[tuple[str, ...]] = []
    for r_idx, row in enumerate(rows):
        json_rows.append(tuple(row))
        for c_idx, cell in enumerate(row):
            cells.append(TableCell(row=r_idx, col=c_idx, text=cell))
    return TableBlock(
        page_number=page_number,
        table_index=table_index,
        row_count=len(rows),
        col_count=max(len(r) for r in rows) if rows else 0,
        cells=tuple(cells),
        markdown="",
        json_data=tuple(json_rows),
        caption=caption,
        confidence=confidence,
        extraction_engine="pymupdf",
        bbox=BoundingBox(x0=0, y0=0, x1=100, y1=100),
    )


# ---------------------------------------------------------------------------
# build_table_chunk — valid table
# ---------------------------------------------------------------------------


def test_build_table_chunk_valid_structure():
    table = _make_table(
        rows=[["Product", "Price", "Stock"], ["Widget A", "9.99", "100"], ["Widget B", "14.99", "50"]],
        page_number=3,
        caption="Product catalog",
    )
    result = build_table_chunk(table, section_context="Pricing Overview")

    assert result.is_valid is True
    assert "[Table 1 on page 3]" in result.text
    assert "Product catalog" in result.text
    assert "Section: Pricing Overview" in result.text
    assert "| Product | Price | Stock |" in result.text
    assert "| Widget A | 9.99 | 100 |" in result.text


def test_build_table_chunk_metadata_keys():
    table = _make_table(
        rows=[["Name", "Value"], ["Alpha", "1"], ["Beta", "2"]],
        table_index=2,
        page_number=5,
        caption="Summary",
    )
    result = build_table_chunk(table)

    meta = result.table_metadata
    assert meta["table_index"] == 2
    assert meta["page_number"] == 5
    assert meta["row_count"] == 3
    assert meta["col_count"] == 2
    assert meta["caption"] == "Summary"
    assert meta["headers"] == ["Name", "Value"]
    assert meta["extraction_engine"] == "pymupdf"
    assert meta["is_valid"] is True


def test_build_table_chunk_no_caption():
    table = _make_table(rows=[["A", "B"], ["1", "2"]])
    result = build_table_chunk(table)
    assert "[Table 1 on page 1]" in result.text
    assert "None" not in result.text


def test_build_table_chunk_no_section_context():
    table = _make_table(rows=[["A", "B"], ["1", "2"]])
    result = build_table_chunk(table, section_context=None)
    assert "Section:" not in result.text


def test_build_table_chunk_table_index_in_text():
    table = _make_table(rows=[["X"]], table_index=4, page_number=7)
    result = build_table_chunk(table)
    assert "[Table 5 on page 7]" in result.text


# ---------------------------------------------------------------------------
# build_table_chunk — fallback for low-confidence or degenerate tables
# ---------------------------------------------------------------------------


def test_build_table_chunk_low_confidence_fallback():
    table = _make_table(rows=[["A", "B"]], confidence=0.1)
    result = build_table_chunk(table)
    assert result.is_valid is False
    assert "[Table 1 on page 1]" in result.text
    # Fallback still contains cell text
    assert "A" in result.text or "B" in result.text


def test_build_table_chunk_zero_confidence_fallback():
    table = _make_table(rows=[], confidence=0.0)
    result = build_table_chunk(table)
    assert result.is_valid is False


def test_build_table_chunk_metadata_marks_invalid():
    table = _make_table(rows=[["Only"]], confidence=0.05)
    result = build_table_chunk(table)
    assert result.table_metadata["is_valid"] is False


# ---------------------------------------------------------------------------
# build_table_chunk — section_context propagated into metadata
# ---------------------------------------------------------------------------


def test_build_table_chunk_section_context_in_metadata():
    table = _make_table(rows=[["Col"], ["val"]])
    result = build_table_chunk(table, section_context="Chapter 3")
    assert result.table_metadata["section_context"] == "Chapter 3"


def test_build_table_chunk_no_section_context_in_metadata():
    table = _make_table(rows=[["Col"], ["val"]])
    result = build_table_chunk(table, section_context=None)
    assert result.table_metadata["section_context"] is None


# ---------------------------------------------------------------------------
# build_docx_table_chunk
# ---------------------------------------------------------------------------


def test_build_docx_table_chunk_valid():
    rows = [["Quarter", "Revenue", "Profit"], ["Q1", "1M", "200K"], ["Q2", "1.2M", "250K"]]
    result = build_docx_table_chunk(rows, table_index=0, page_number=2, section_context="Financials")

    assert result.is_valid is True
    assert "[Table 1 on page 2]" in result.text
    assert "Section: Financials" in result.text
    assert "| Quarter | Revenue | Profit |" in result.text
    assert result.table_metadata["row_count"] == 3
    assert result.table_metadata["col_count"] == 3
    assert result.table_metadata["headers"] == ["Quarter", "Revenue", "Profit"]
    assert result.table_metadata["extraction_engine"] == "python-docx"


def test_build_docx_table_chunk_empty_returns_invalid():
    result = build_docx_table_chunk([], table_index=0, page_number=1)
    assert result.is_valid is False
    assert result.table_metadata["row_count"] == 0


def test_build_docx_table_chunk_all_empty_cells_returns_invalid():
    rows = [["", ""], ["", ""]]
    result = build_docx_table_chunk(rows, table_index=0, page_number=1)
    assert result.is_valid is False


def test_build_docx_table_chunk_no_section_context():
    rows = [["H1", "H2"], ["v1", "v2"]]
    result = build_docx_table_chunk(rows, table_index=1, page_number=3)
    assert "Section:" not in result.text


def test_build_docx_table_chunk_jagged_rows_padded():
    # Rows of unequal length should be padded to equal width.
    rows = [["A", "B", "C"], ["x"]]
    result = build_docx_table_chunk(rows, table_index=0, page_number=1)
    assert result.table_metadata["col_count"] == 3
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# Markdown output correctness
# ---------------------------------------------------------------------------


def test_table_chunk_markdown_separator_row():
    table = _make_table(rows=[["H1", "H2"], ["r1", "r2"]])
    result = build_table_chunk(table)
    lines = result.text.split("\n")
    separator_lines = [l for l in lines if "---" in l]
    assert len(separator_lines) == 1
    assert "| --- | --- |" in separator_lines[0]


def test_table_chunk_header_row_is_first():
    table = _make_table(rows=[["Name", "Age"], ["Alice", "30"]])
    result = build_table_chunk(table)
    first_pipe_line = next(l for l in result.text.split("\n") if "|" in l)
    assert "Name" in first_pipe_line
    assert "Age" in first_pipe_line
