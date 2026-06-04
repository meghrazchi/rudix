from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.domains.documents.services.text_extraction import ExtractedSection


class DocumentProfile(StrEnum):
    text_based = "text_based"
    scanned = "scanned"
    mixed = "mixed"
    table_heavy = "table_heavy"
    figure_heavy = "figure_heavy"
    form_like = "form_like"
    encrypted = "encrypted"
    corrupted = "corrupted"
    unsupported = "unsupported"


@dataclass(frozen=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def area(self) -> float:
        return max(0.0, (self.x1 - self.x0) * (self.y1 - self.y0))


@dataclass(frozen=True)
class TextBlock:
    page_number: int
    text: str
    bbox: BoundingBox | None
    block_type: str
    confidence: float = 1.0


@dataclass(frozen=True)
class TableCell:
    row: int
    col: int
    text: str


@dataclass(frozen=True)
class TableBlock:
    page_number: int
    table_index: int
    row_count: int
    col_count: int
    cells: tuple[TableCell, ...]
    markdown: str
    json_data: tuple[tuple[str, ...], ...]
    caption: str | None
    confidence: float
    extraction_engine: str
    bbox: BoundingBox | None


@dataclass(frozen=True)
class ImageBlock:
    page_number: int
    block_type: str
    bbox: BoundingBox | None
    caption: str | None
    confidence: float


@dataclass
class PageExtractionResult:
    page_number: int
    text_blocks: list[TextBlock]
    table_blocks: list[TableBlock]
    image_blocks: list[ImageBlock]
    char_count: int
    page_width: float
    page_height: float
    text_coverage_ratio: float
    image_coverage_ratio: float
    requires_ocr: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def has_tables(self) -> bool:
        return len(self.table_blocks) > 0

    @property
    def has_images(self) -> bool:
        return len(self.image_blocks) > 0


@dataclass
class ExtractionResult:
    document_profile: DocumentProfile
    page_count: int
    pages: list[PageExtractionResult]
    total_text_blocks: int
    total_table_blocks: int
    total_image_blocks: int
    warnings: list[str]
    extraction_engine: str
    extraction_confidence: float
    duration_ms: int
    is_encrypted: bool = False

    def to_sections(self) -> list[ExtractedSection]:
        """Convert to ExtractedSection list for downstream chunking compatibility."""
        sections: list[ExtractedSection] = []
        for page in self.pages:
            parts: list[str] = []

            for block in page.text_blocks:
                stripped = block.text.strip()
                if stripped:
                    parts.append(stripped)

            for table in page.table_blocks:
                stripped = table.markdown.strip()
                if stripped:
                    parts.append(stripped)

            for img in page.image_blocks:
                ref = _build_visual_reference(img)
                if ref:
                    parts.append(ref)

            combined = "\n\n".join(parts).strip()
            sections.append(
                ExtractedSection(
                    page_number=page.page_number,
                    text=combined,
                    char_count=len(combined),
                )
            )
        return sections

    def to_snapshot(self) -> dict:
        """Produce a serializable diagnostics snapshot safe for DB storage (no document text)."""
        return {
            "document_profile": self.document_profile.value,
            "page_count": self.page_count,
            "total_text_blocks": self.total_text_blocks,
            "total_table_blocks": self.total_table_blocks,
            "total_image_blocks": self.total_image_blocks,
            "extraction_engine": self.extraction_engine,
            "extraction_confidence": round(self.extraction_confidence, 4),
            "duration_ms": self.duration_ms,
            "is_encrypted": self.is_encrypted,
            "warnings": self.warnings,
            "pages": [
                {
                    "page_number": p.page_number,
                    "char_count": p.char_count,
                    "text_coverage_ratio": round(p.text_coverage_ratio, 4),
                    "image_coverage_ratio": round(p.image_coverage_ratio, 4),
                    "requires_ocr": p.requires_ocr,
                    "text_block_count": len(p.text_blocks),
                    "table_block_count": len(p.table_blocks),
                    "image_block_count": len(p.image_blocks),
                    "warnings": p.warnings,
                }
                for p in self.pages
            ],
        }


def _build_visual_reference(img: ImageBlock) -> str:
    label = img.block_type.replace("_", " ").title()
    if img.caption:
        return f"[{label} on page {img.page_number} — {img.caption}]"
    return f"[{label} on page {img.page_number}]"
