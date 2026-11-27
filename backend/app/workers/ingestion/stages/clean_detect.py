"""clean_detect stage: text cleaning and language detection (R06-01).

Reads the extract pages, writes cleaned pages as artifact parts, and keeps the cleaning
statistics in the stage metrics so ``TextCleaningStats`` can be rebuilt on resume.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any

from app.domains.documents.services.language_detection_service import (
    confidence_bucket as _language_confidence_bucket,
)
from app.domains.documents.services.language_detection_service import (
    detect_language_from_text as _detect_language_from_text,
)
from app.domains.documents.services.text_normalization import (
    TextCleaningStats,
    clean_extracted_sections,
)
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.documents import load_document
from app.workers.ingestion.errors import DocumentPipelinePermanentError
from app.workers.ingestion.pages import page_record, read_pages, to_sections, write_pages
from app.workers.ingestion.stages.base import StageName, StageOutcome


def cleaning_stats_from_metrics(metrics: dict[str, Any]) -> TextCleaningStats:
    values = metrics.get("cleaning", {})
    names = {item.name for item in fields(TextCleaningStats)}
    return TextCleaningStats(**{key: int(value) for key, value in values.items() if key in names})


async def run(ctx: StageContext) -> StageOutcome:
    pages = await read_pages(ctx, StageName.extract)
    cleaned, stats = clean_extracted_sections(to_sections(pages))
    if not any(section.text for section in cleaned):
        raise DocumentPipelinePermanentError(
            stage="clean",
            code="EMPTY_AFTER_CLEANING",
            category="validation",
            message="extracted document contains no text after cleaning",
        )
    document = await load_document(ctx)
    language = await _detect_language(ctx, document, cleaned)
    parts = await write_pages(
        ctx, StageName.clean_detect, [page_record(section) for section in cleaned]
    )
    return StageOutcome(
        metrics={
            "page_count": len(cleaned),
            "artifact_parts": parts,
            "cleaning": asdict(stats),
            "language": language,
        }
    )


async def _detect_language(ctx: StageContext, document: Any, cleaned: list[Any]) -> str | None:
    """Detect on cleaned text unless an admin override is set (F230)."""
    if document.language_source == "admin_override":
        return document.language
    ctx.current_stage = "detect_language"
    result = _detect_language_from_text("\n".join(s.text for s in cleaned if s.text))
    if result.language_code is None and document.language_source == "upload_provided":
        return document.language
    language = result.language_code or document.language
    source = (
        "upload_provided"
        if document.language_source == "upload_provided" and document.language is not None
        else "auto_detected"
    )
    deps = ctx.deps
    async with deps.SessionLocal() as session:
        await deps.document_repository.update_document_language(
            session,
            document_id=ctx.document_id,
            language=language,
            language_confidence=result.confidence if result.language_code is not None else None,
            language_source=source,
        )
        await session.commit()
    bucket = _language_confidence_bucket(result.confidence)
    ctx.log_stage(
        "detect_language",
        "completed",
        language_code=language,
        language_source=source,
        confidence_bucket=bucket,
    )
    await ctx.recorder.emit_stage(
        stage="detect_language",
        stage_status="completed",
        outputs={"language_code": language, "language_source": source, "confidence_bucket": bucket},
    )
    return language
