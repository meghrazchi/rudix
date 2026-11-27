"""Page artifacts: one part per page, oversize page text split across parts (R06-01).

Pages are the extract and clean_detect output. A page whose compressed record exceeds
``INGEST_ARTIFACT_MAX_PART_BYTES`` is written as several consecutive parts that carry a
slice of the text each (``fragment``/``fragments``); ``read_pages`` joins them again.
"""

from __future__ import annotations

import math
from typing import Any

from app.core.config import settings
from app.domains.documents.extraction.models import BoundingBox, TableBlock, TableCell
from app.domains.documents.services.text_extraction import ExtractedSection
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.store import encode_artifact

_MAX_SPLIT_ROUNDS = 8


def _split_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    limit = settings.ingest_artifact_max_part_bytes
    size = len(encode_artifact(page))
    if size <= limit:
        return [page]
    text = str(page.get("text") or "")
    count = max(2, math.ceil(size / limit) + 1)
    for _ in range(_MAX_SPLIT_ROUNDS):
        step = max(1, math.ceil(len(text) / count))
        slices = [text[start : start + step] for start in range(0, len(text), step)] or [""]
        fragments = [
            {**(page if index == 0 else {"page_number": page["page_number"]}), "text": piece}
            for index, piece in enumerate(slices)
        ]
        for index, fragment in enumerate(fragments):
            fragment["fragment"], fragment["fragments"] = index, len(fragments)
        if all(len(encode_artifact(item)) <= limit for item in fragments):
            return fragments
        count *= 2
    # Still too large (non-text fields): let the store reject it with a safe error code.
    return [page]


async def write_pages(ctx: StageContext, stage: str, pages: list[dict[str, Any]]) -> int:
    parts: dict[int, Any] = {}
    for page in pages:
        for fragment in _split_page(page):
            parts[len(parts)] = fragment
    await ctx.store.write_artifacts(stage, parts, replace_stage=True)
    return len(parts)


async def read_pages(ctx: StageContext, stage: str) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    async for record in ctx.store.iter_artifacts(stage):
        if int(record.get("fragment", 0)) > 0 and pages:
            pages[-1]["text"] = str(pages[-1]["text"]) + str(record.get("text") or "")
            continue
        record.pop("fragment", None)
        record.pop("fragments", None)
        pages.append(record)
    return pages


def page_record(section: Any, **extra: Any) -> dict[str, Any]:
    return {
        "page_number": section.page_number,
        "text": section.text,
        "char_count": section.char_count,
        **extra,
    }


def to_sections(pages: list[dict[str, Any]]) -> list[ExtractedSection]:
    return [
        ExtractedSection(
            page_number=int(page["page_number"]),
            text=str(page["text"]),
            char_count=int(page["char_count"]),
        )
        for page in pages
    ]


def table_to_dict(table: TableBlock) -> dict[str, Any]:
    return {
        "page_number": table.page_number,
        "table_index": table.table_index,
        "row_count": table.row_count,
        "col_count": table.col_count,
        "cells": [{"row": c.row, "col": c.col, "text": c.text} for c in table.cells],
        "markdown": table.markdown,
        "json_data": [list(row) for row in table.json_data],
        "caption": table.caption,
        "confidence": table.confidence,
        "extraction_engine": table.extraction_engine,
        "bbox": (
            None
            if table.bbox is None
            else {
                "x0": table.bbox.x0,
                "y0": table.bbox.y0,
                "x1": table.bbox.x1,
                "y1": table.bbox.y1,
            }
        ),
    }


def table_from_dict(data: dict[str, Any]) -> TableBlock:
    bbox = data.get("bbox")
    return TableBlock(
        page_number=int(data["page_number"]),
        table_index=int(data["table_index"]),
        row_count=int(data["row_count"]),
        col_count=int(data["col_count"]),
        cells=tuple(TableCell(**cell) for cell in data.get("cells", [])),
        markdown=str(data["markdown"]),
        json_data=tuple(tuple(row) for row in data.get("json_data", [])),
        caption=data.get("caption"),
        confidence=float(data["confidence"]),
        extraction_engine=str(data["extraction_engine"]),
        bbox=BoundingBox(**bbox) if bbox else None,
    )
