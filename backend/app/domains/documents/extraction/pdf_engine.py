from __future__ import annotations

import time

import fitz

from app.domains.documents.extraction.models import (
    BoundingBox,
    DocumentProfile,
    ExtractionResult,
    ImageBlock,
    PageExtractionResult,
    TableBlock,
    TableCell,
    TextBlock,
)
from app.domains.documents.extraction.pdf_classifier import classify_document_profile

_ENGINE_NAME = "pymupdf"
_TABLE_OVERLAP_THRESHOLD = 0.60


def extract_pdf(
    content: bytes,
    *,
    min_chars_per_page: int = 30,
    max_pages: int | None = None,
    enable_table_extraction: bool = True,
    enable_image_extraction: bool = True,
) -> ExtractionResult:
    started_at = time.monotonic()
    warnings: list[str] = []

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"malformed or corrupted PDF: {exc}") from exc

    try:
        if doc.is_encrypted and doc.needs_pass:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            return ExtractionResult(
                document_profile=DocumentProfile.encrypted,
                page_count=doc.page_count,
                pages=[],
                total_text_blocks=0,
                total_table_blocks=0,
                total_image_blocks=0,
                warnings=["Document is password-protected and cannot be extracted"],
                extraction_engine=_ENGINE_NAME,
                extraction_confidence=0.0,
                duration_ms=duration_ms,
                is_encrypted=True,
            )

        total_page_count = doc.page_count
        pages_to_process = total_page_count
        if max_pages is not None:
            pages_to_process = min(total_page_count, max_pages)
            if pages_to_process < total_page_count:
                warnings.append(
                    f"Only {pages_to_process} of {total_page_count} pages extracted "
                    f"(limit: {max_pages})"
                )

        pages: list[PageExtractionResult] = []
        for page_idx in range(pages_to_process):
            try:
                fitz_page = doc[page_idx]
                page_result = _extract_page(
                    fitz_page,
                    page_number=page_idx + 1,
                    min_chars_per_page=min_chars_per_page,
                    enable_table_extraction=enable_table_extraction,
                    enable_image_extraction=enable_image_extraction,
                )
                pages.append(page_result)
            except Exception as exc:
                page_number = page_idx + 1
                warning = f"Page {page_number} extraction failed: {exc}"
                warnings.append(warning)
                pages.append(_empty_page_result(page_number, warning=warning))

        document_profile = classify_document_profile(pages, min_chars_per_page=min_chars_per_page)
        total_text_blocks = sum(len(p.text_blocks) for p in pages)
        total_table_blocks = sum(len(p.table_blocks) for p in pages)
        total_image_blocks = sum(len(p.image_blocks) for p in pages)

        usable_pages = sum(1 for p in pages if p.char_count > 0 or p.has_images)
        extraction_confidence = usable_pages / len(pages) if pages else 0.0

        duration_ms = int((time.monotonic() - started_at) * 1000)
        return ExtractionResult(
            document_profile=document_profile,
            page_count=total_page_count,
            pages=pages,
            total_text_blocks=total_text_blocks,
            total_table_blocks=total_table_blocks,
            total_image_blocks=total_image_blocks,
            warnings=warnings,
            extraction_engine=_ENGINE_NAME,
            extraction_confidence=extraction_confidence,
            duration_ms=duration_ms,
        )
    finally:
        doc.close()


def _extract_page(
    page: fitz.Page,
    *,
    page_number: int,
    min_chars_per_page: int,
    enable_table_extraction: bool,
    enable_image_extraction: bool,
) -> PageExtractionResult:
    warnings: list[str] = []
    page_rect = page.rect
    page_area = (
        page_rect.width * page_rect.height if page_rect.width > 0 and page_rect.height > 0 else 1.0
    )

    table_blocks: list[TableBlock] = []
    table_bboxes: list[fitz.Rect] = []
    if enable_table_extraction:
        table_blocks, table_bboxes, table_warnings = _extract_tables(page, page_number)
        warnings.extend(table_warnings)

    image_blocks: list[ImageBlock] = []
    image_area = 0.0
    if enable_image_extraction:
        image_blocks, image_area = _extract_images(page, page_number)

    text_blocks, total_chars, text_area = _extract_text_blocks(
        page, page_number, excluded_rects=table_bboxes
    )

    table_char_count = sum(len(cell.text) for tb in table_blocks for cell in tb.cells)
    char_count = total_chars + table_char_count

    text_coverage_ratio = min(1.0, text_area / page_area)
    image_coverage_ratio = min(1.0, image_area / page_area)
    requires_ocr = char_count < min_chars_per_page

    return PageExtractionResult(
        page_number=page_number,
        text_blocks=text_blocks,
        table_blocks=table_blocks,
        image_blocks=image_blocks,
        char_count=char_count,
        page_width=page_rect.width,
        page_height=page_rect.height,
        text_coverage_ratio=text_coverage_ratio,
        image_coverage_ratio=image_coverage_ratio,
        requires_ocr=requires_ocr,
        warnings=warnings,
    )


def _extract_text_blocks(
    page: fitz.Page,
    page_number: int,
    *,
    excluded_rects: list[fitz.Rect],
) -> tuple[list[TextBlock], int, float]:
    raw_blocks = page.get_text("blocks")
    text_blocks: list[TextBlock] = []
    total_chars = 0
    text_area = 0.0

    for block in raw_blocks:
        if len(block) < 7:
            continue
        x0, y0, x1, y1, text, _block_no, block_type_code = block[:7]
        if block_type_code != 0:
            continue

        normalized = text.strip()
        if not normalized:
            continue

        block_rect = fitz.Rect(x0, y0, x1, y1)
        if _is_substantially_covered(block_rect, excluded_rects):
            continue

        text_blocks.append(
            TextBlock(
                page_number=page_number,
                text=normalized,
                bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
                block_type="text",
                confidence=1.0,
            )
        )
        total_chars += len(normalized)
        text_area += block_rect.get_area()

    return text_blocks, total_chars, text_area


def _extract_tables(
    page: fitz.Page,
    page_number: int,
) -> tuple[list[TableBlock], list[fitz.Rect], list[str]]:
    warnings: list[str] = []
    table_blocks: list[TableBlock] = []
    table_bboxes: list[fitz.Rect] = []

    try:
        table_finder = page.find_tables()
        for table_idx, table in enumerate(table_finder.tables):
            try:
                extracted = table.extract()
                if not extracted:
                    continue

                rows = len(extracted)
                cols = max((len(row) for row in extracted), default=0)
                if rows == 0 or cols == 0:
                    continue

                cells: list[TableCell] = []
                json_rows: list[tuple[str, ...]] = []
                for r_idx, row in enumerate(extracted):
                    row_cells: list[str] = []
                    for c_idx, cell_val in enumerate(row):
                        cell_text = (cell_val or "").strip()
                        cells.append(TableCell(row=r_idx, col=c_idx, text=cell_text))
                        row_cells.append(cell_text)
                    json_rows.append(tuple(row_cells))

                markdown = _rows_to_markdown(extracted)
                bbox_rect = fitz.Rect(table.bbox)
                table_bboxes.append(bbox_rect)

                table_blocks.append(
                    TableBlock(
                        page_number=page_number,
                        table_index=table_idx,
                        row_count=rows,
                        col_count=cols,
                        cells=tuple(cells),
                        markdown=markdown,
                        json_data=tuple(json_rows),
                        caption=None,
                        confidence=0.9,
                        extraction_engine=_ENGINE_NAME,
                        bbox=BoundingBox(*table.bbox),
                    )
                )
            except Exception as exc:
                warnings.append(f"Table {table_idx + 1} on page {page_number} failed: {exc}")
    except AttributeError:
        warnings.append(
            f"Table extraction unavailable on page {page_number} "
            "(PyMuPDF version may not support find_tables)"
        )
    except Exception as exc:
        warnings.append(f"Table extraction failed on page {page_number}: {exc}")

    return table_blocks, table_bboxes, warnings


def _extract_images(
    page: fitz.Page,
    page_number: int,
) -> tuple[list[ImageBlock], float]:
    image_blocks: list[ImageBlock] = []
    total_image_area = 0.0

    try:
        images = page.get_images(full=True)
        for img_info in images:
            bbox: BoundingBox | None = None
            try:
                raw_bbox = page.get_image_bbox(img_info)
                if isinstance(raw_bbox, fitz.Rect) and not raw_bbox.is_empty:
                    bbox = BoundingBox(
                        x0=raw_bbox.x0,
                        y0=raw_bbox.y0,
                        x1=raw_bbox.x1,
                        y1=raw_bbox.y1,
                    )
                    total_image_area += raw_bbox.get_area()
            except Exception:
                pass

            image_blocks.append(
                ImageBlock(
                    page_number=page_number,
                    block_type="image",
                    bbox=bbox,
                    caption=None,
                    confidence=0.95 if bbox is not None else 0.5,
                )
            )
    except Exception:
        pass

    return image_blocks, total_image_area


def _rows_to_markdown(rows: list[list[str | None]]) -> str:
    if not rows:
        return ""

    normalized: list[list[str]] = [[str(cell or "").strip() for cell in row] for row in rows]
    col_count = max((len(row) for row in normalized), default=0)
    if col_count == 0:
        return ""

    padded = [row + [""] * (col_count - len(row)) for row in normalized]
    lines: list[str] = []
    header = padded[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in padded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _is_substantially_covered(
    block_rect: fitz.Rect,
    excluded_rects: list[fitz.Rect],
    threshold: float = _TABLE_OVERLAP_THRESHOLD,
) -> bool:
    block_area = block_rect.get_area()
    if block_area <= 0:
        return False
    for excl in excluded_rects:
        intersection = block_rect & excl
        if not intersection.is_empty:
            if intersection.get_area() / block_area >= threshold:
                return True
    return False


def _empty_page_result(page_number: int, *, warning: str) -> PageExtractionResult:
    return PageExtractionResult(
        page_number=page_number,
        text_blocks=[],
        table_blocks=[],
        image_blocks=[],
        char_count=0,
        page_width=0.0,
        page_height=0.0,
        text_coverage_ratio=0.0,
        image_coverage_ratio=0.0,
        requires_ocr=True,
        warnings=[warning],
    )
