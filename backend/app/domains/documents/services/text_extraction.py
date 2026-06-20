from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import fitz  # type: ignore[import-untyped]
from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph


@dataclass(frozen=True)
class ExtractedSection:
    page_number: int
    text: str
    char_count: int


def _coerce_section(page_number: int, text: str) -> ExtractedSection:
    normalized_text = text.strip()
    return ExtractedSection(
        page_number=page_number,
        text=normalized_text,
        char_count=len(normalized_text),
    )


def _extract_pdf_sections(content: bytes) -> list[ExtractedSection]:
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ValueError("malformed pdf file") from exc

    sections: list[ExtractedSection] = []
    try:
        for page_index, page in enumerate(document, start=1):
            try:
                text = page.get_text("text")
            except Exception as exc:
                raise ValueError(f"failed to extract text from pdf page {page_index}") from exc
            sections.append(_coerce_section(page_index, text))
    finally:
        document.close()
    return sections


def _extract_txt_sections(content: bytes) -> list[ExtractedSection]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        # Keep extraction robust for mixed/legacy byte streams.
        text = content.decode("utf-8", errors="replace")
    return [_coerce_section(1, text)]


def _extract_table_text(table: Table) -> str:
    row_texts: list[str] = []
    for row in table.rows:
        cell_values = [cell.text.strip() for cell in row.cells]
        row_text = " | ".join(value for value in cell_values if value)
        if row_text:
            row_texts.append(row_text)
    return "\n".join(row_texts)


def _iter_docx_blocks(doc: Any) -> list[Paragraph | Table]:
    blocks: list[Paragraph | Table] = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.lower()
        if tag.endswith("}p"):
            blocks.append(Paragraph(child, doc))
        elif tag.endswith("}tbl"):
            blocks.append(Table(child, doc))
    return blocks


def _extract_docx_sections(content: bytes) -> list[ExtractedSection]:
    try:
        doc = DocxDocument(BytesIO(content))
    except Exception as exc:
        raise ValueError("malformed docx file") from exc

    sections: list[ExtractedSection] = []
    page_number = 1
    for block in _iter_docx_blocks(doc):
        text: str
        if isinstance(block, Paragraph):
            text = block.text
        else:
            text = _extract_table_text(block)
        normalized = text.strip()
        if not normalized:
            continue
        sections.append(_coerce_section(page_number, normalized))
        page_number += 1

    return sections


def extract_pdf_pages_native(content: bytes) -> list[ExtractedSection]:
    """Extract all PDF pages natively without raising on empty text.

    Used before OCR detection so scanned pages (empty text) are still returned
    and can be passed to the OCR detection and extraction stages.
    """
    return _extract_pdf_sections(content)


def extract_text_sections(*, file_type: str, content: bytes) -> list[ExtractedSection]:
    normalized_type = file_type.strip().lower()
    if normalized_type == "pdf":
        sections = _extract_pdf_sections(content)
    elif normalized_type == "txt":
        sections = _extract_txt_sections(content)
    elif normalized_type == "docx":
        sections = _extract_docx_sections(content)
    else:
        raise ValueError(f"unsupported file type: {file_type}")

    non_empty_sections = [section for section in sections if section.text]
    if not non_empty_sections:
        raise ValueError("extracted document contains no text")
    return sections
