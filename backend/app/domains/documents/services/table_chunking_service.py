"""Table chunking service — F298.

Converts extracted TableBlock objects into structured text chunks that preserve
table structure for embedding while keeping full metadata for citation display.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.documents.extraction.models import TableBlock

# Tables below this confidence or with fewer than these dimensions use a flattened
# fallback format rather than structured markdown.
_MIN_CONFIDENCE = 0.3
_MIN_ROWS = 1
_MIN_COLS = 1


@dataclass(frozen=True)
class TableChunkResult:
    """Output of converting a TableBlock to a chunk-ready form."""

    text: str
    table_metadata: dict
    is_valid: bool


def build_table_chunk(
    table: TableBlock,
    *,
    section_context: str | None = None,
) -> TableChunkResult:
    """Convert a TableBlock into structured chunk text and metadata dict.

    The structured text is designed to be informative for vector embedding:
    it includes the caption, section context, header row, and all data rows.
    Malformed or low-confidence tables fall back to flattened text so ingestion
    never fails.
    """
    is_valid = (
        table.confidence >= _MIN_CONFIDENCE
        and table.row_count >= _MIN_ROWS
        and table.col_count >= _MIN_COLS
        and len(table.cells) > 0
    )

    if is_valid:
        text = _build_structured_text(table, section_context=section_context)
    else:
        text = _build_fallback_text(table, section_context=section_context)

    headers = _extract_headers(table)
    metadata: dict = {
        "table_index": table.table_index,
        "page_number": table.page_number,
        "row_count": table.row_count,
        "col_count": table.col_count,
        "caption": table.caption,
        "headers": headers,
        "section_context": section_context,
        "confidence": round(table.confidence, 4),
        "extraction_engine": table.extraction_engine,
        "is_valid": is_valid,
    }

    return TableChunkResult(text=text, table_metadata=metadata, is_valid=is_valid)


def build_docx_table_chunk(
    rows: list[list[str]],
    *,
    table_index: int,
    page_number: int,
    section_context: str | None = None,
) -> TableChunkResult:
    """Convert a DOCX table (list of row lists) into structured chunk text and metadata.

    Used by the document worker when processing DOCX files with table blocks.
    """
    if not rows or not any(any(cell for cell in row) for row in rows):
        return TableChunkResult(
            text="[Empty table]",
            table_metadata={
                "table_index": table_index,
                "page_number": page_number,
                "row_count": 0,
                "col_count": 0,
                "caption": None,
                "headers": [],
                "section_context": section_context,
                "confidence": 0.0,
                "extraction_engine": "python-docx",
                "is_valid": False,
            },
            is_valid=False,
        )

    normalized = [[str(cell or "").strip() for cell in row] for row in rows]
    col_count = max(len(row) for row in normalized)
    padded = [row + [""] * (col_count - len(row)) for row in normalized]

    headers = padded[0] if padded else []
    text = _format_structured_text(
        table_index=table_index,
        page_number=page_number,
        caption=None,
        section_context=section_context,
        rows=padded,
    )

    metadata: dict = {
        "table_index": table_index,
        "page_number": page_number,
        "row_count": len(rows),
        "col_count": col_count,
        "caption": None,
        "headers": headers,
        "section_context": section_context,
        "confidence": 0.8,
        "extraction_engine": "python-docx",
        "is_valid": True,
    }

    return TableChunkResult(text=text, table_metadata=metadata, is_valid=True)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _extract_headers(table: TableBlock) -> list[str]:
    """Return the first row cell texts as the header list."""
    if not table.json_data:
        return []
    first_row = table.json_data[0]
    return [str(cell or "").strip() for cell in first_row]


def _build_structured_text(table: TableBlock, *, section_context: str | None) -> str:
    rows = [[str(cell or "").strip() for cell in row] for row in table.json_data]
    return _format_structured_text(
        table_index=table.table_index,
        page_number=table.page_number,
        caption=table.caption,
        section_context=section_context,
        rows=rows,
    )


def _format_structured_text(
    *,
    table_index: int,
    page_number: int,
    caption: str | None,
    section_context: str | None,
    rows: list[list[str]],
) -> str:
    parts: list[str] = []

    header = f"[Table {table_index + 1} on page {page_number}]"
    if caption:
        header = f"{header}: {caption}"
    parts.append(header)

    if section_context:
        parts.append(f"Section: {section_context}")

    if rows:
        col_count = max(len(row) for row in rows)
        padded = [row + [""] * (col_count - len(row)) for row in rows]
        parts.append(_rows_to_markdown(padded))

    return "\n".join(parts)


def _build_fallback_text(table: TableBlock, *, section_context: str | None) -> str:
    """Flatten all cell text for low-confidence or degenerate tables."""
    parts: list[str] = [f"[Table {table.table_index + 1} on page {table.page_number}]"]
    if section_context:
        parts.append(f"Section: {section_context}")
    cell_texts = [cell.text for cell in table.cells if cell.text]
    if cell_texts:
        parts.append(" | ".join(cell_texts))
    return "\n".join(parts)


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    col_count = max(len(row) for row in rows)
    if col_count == 0:
        return ""
    padded = [row + [""] * (col_count - len(row)) for row in rows]
    lines: list[str] = []
    lines.append("| " + " | ".join(padded[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in padded[0]) + " |")
    for row in padded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
