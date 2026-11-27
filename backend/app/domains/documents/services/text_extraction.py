from __future__ import annotations

import codecs
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import IO, Any

import fitz  # type: ignore[import-untyped]
from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

# Extractors accept the content in memory or a path to it (R06-02, additive): workers pass
# the temporary file the stored object was streamed to, so PDF and TXT are never held in
# memory whole. DOCX (python-docx) still loads the whole file; the upload limit bounds it.
DocumentSource = bytes | Path


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


def open_pdf(source: DocumentSource) -> Any:
    """Open a PDF from bytes or from a path (pages are then loaded on demand)."""
    try:
        if isinstance(source, Path):
            return fitz.open(source)
        return fitz.open(stream=source, filetype="pdf")
    except Exception as exc:
        raise ValueError("malformed pdf file") from exc


def iter_pdf_sections(source: DocumentSource) -> Iterator[ExtractedSection]:
    """One section per page, produced page by page."""
    document = open_pdf(source)
    try:
        for page_index in range(document.page_count):
            try:
                text = document[page_index].get_text("text")
            except Exception as exc:
                raise ValueError(f"failed to extract text from pdf page {page_index + 1}") from exc
            yield _coerce_section(page_index + 1, text)
    finally:
        document.close()


def _extract_pdf_sections(content: DocumentSource) -> list[ExtractedSection]:
    return list(iter_pdf_sections(content))


def _cut_position(buffer: str, limit: int) -> int:
    """End of the next segment: after the last newline (else space) in the window."""
    for separator in ("\n", " "):
        position = buffer.rfind(separator, 0, limit)
        if position >= limit // 2:
            return position + 1
    return limit


def _open_binary(source: DocumentSource) -> IO[bytes]:
    return source.open("rb") if isinstance(source, Path) else BytesIO(source)


def iter_txt_sections(
    source: DocumentSource, *, segment_chars: int | None = None
) -> Iterator[ExtractedSection]:
    """Decode UTF-8 text in segments of at most ``INGEST_TEXT_SEGMENT_CHARS`` characters.

    Invalid bytes are replaced, as the whole-file decode did. A text shorter than one
    segment is one section (page 1), exactly as before; a longer one becomes page-like
    sections 1..n cut at line (else word) boundaries.
    """
    from app.core.config import settings  # lazy: this module imports without settings

    limit = segment_chars or settings.ingest_text_segment_chars
    read_size = settings.ingest_download_chunk_bytes
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buffer = ""
    page_number = 0
    with _open_binary(source) as handle:
        while True:
            data = handle.read(read_size)
            buffer += decoder.decode(data, final=not data)
            while len(buffer) > limit:
                cut = _cut_position(buffer, limit)
                page_number += 1
                yield _coerce_section(page_number, buffer[:cut])
                buffer = buffer[cut:]
            if not data:
                break
    if buffer or page_number == 0:
        yield _coerce_section(page_number + 1, buffer)


def _extract_txt_sections(content: DocumentSource) -> list[ExtractedSection]:
    return list(iter_txt_sections(content))


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


def _extract_docx_sections(content: DocumentSource) -> list[ExtractedSection]:
    try:
        doc = DocxDocument(str(content) if isinstance(content, Path) else BytesIO(content))
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


def extract_pdf_pages_native(content: DocumentSource) -> list[ExtractedSection]:
    """Extract all PDF pages natively without raising on empty text.

    Used before OCR detection so scanned pages (empty text) are still returned
    and can be passed to the OCR detection and extraction stages.
    """
    return _extract_pdf_sections(content)


def iter_text_sections(*, file_type: str, content: DocumentSource) -> Iterator[ExtractedSection]:
    """Sections one by one; raises ``ValueError`` at the end when none has text."""
    normalized_type = file_type.strip().lower()
    sections: Iterator[ExtractedSection]
    if normalized_type == "pdf":
        sections = iter_pdf_sections(content)
    elif normalized_type == "txt":
        sections = iter_txt_sections(content)
    elif normalized_type == "docx":
        sections = iter(_extract_docx_sections(content))
    else:
        raise ValueError(f"unsupported file type: {file_type}")

    has_text = False
    for section in sections:
        has_text = has_text or bool(section.text)
        yield section
    if not has_text:
        raise ValueError("extracted document contains no text")


def extract_text_sections(*, file_type: str, content: DocumentSource) -> list[ExtractedSection]:
    return list(iter_text_sections(file_type=file_type, content=content))
