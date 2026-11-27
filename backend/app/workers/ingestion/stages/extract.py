"""extract stage: object read, text extraction, OCR detection and OCR (R06-01).

Pipeline-explorer stages ``extract``, ``detect_ocr``, ``ocr``. Writes one artifact part
per page (text plus, for advanced extraction, that page's table blocks and the first 300
characters of its text-block context). Sessions are short and never open during the
object read, extraction, or OCR.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.domains.documents.extraction import extract_document
from app.domains.documents.extraction.models import DocumentProfile, ExtractionResult
from app.domains.documents.services.ocr_detection import detect_ocr_need
from app.domains.documents.services.ocr_language_config import resolve_ocr_tesseract_string
from app.domains.documents.services.ocr_service import merge_ocr_with_sections, run_ocr
from app.domains.documents.services.text_extraction import (
    extract_pdf_pages_native,
    extract_text_sections,
)
from app.workers.base_task import PermanentTaskError, TransientTaskError
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.documents import load_document
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
)
from app.workers.ingestion.pages import page_record, table_to_dict, write_pages
from app.workers.ingestion.stages.base import StageName, StageOutcome
from app.workers.ingestion.stages.ocr import run_ocr_step
from app.workers.ingestion.storage import _read_object_bytes


def _permanent(code: str, message: str, stage: str = "extract") -> DocumentPipelinePermanentError:
    return DocumentPipelinePermanentError(
        stage=stage, code=code, category="validation", message=message
    )


def _read_source(document: Any) -> bytes:
    try:
        return _read_object_bytes(
            bucket=document.storage_bucket, object_key=document.storage_object_key
        )
    except PermanentTaskError as exc:
        raise _permanent("SOURCE_OBJECT_MISSING", str(exc)) from exc
    except TransientTaskError as exc:
        raise DocumentPipelineTransientError(
            stage="extract",
            code="SOURCE_OBJECT_READ_FAILED",
            category="infrastructure",
            message=str(exc),
        ) from exc


async def _advanced(ctx: StageContext, document: Any, content: bytes) -> ExtractionResult:
    try:
        result = extract_document(
            content,
            file_type=document.file_type,
            min_chars_per_page=settings.ocr_min_text_chars_per_page,
            max_pages=settings.pdf_extraction_max_pages,
            enable_table_extraction=settings.pdf_extraction_enable_tables,
            enable_image_extraction=settings.pdf_extraction_enable_images,
        )
    except ValueError as exc:
        raise _permanent("TEXT_EXTRACTION_FAILED", str(exc)) from exc
    if result.document_profile == DocumentProfile.encrypted:
        raise _permanent("PDF_ENCRYPTED", "Document is password-protected and cannot be extracted")
    if result.document_profile == DocumentProfile.corrupted:
        raise _permanent("PDF_CORRUPTED", "Document appears to be corrupted or unreadable")

    deps = ctx.deps
    async with deps.SessionLocal() as session:
        await deps.document_repository.update_document_extraction_snapshot(
            session, document_id=ctx.document_id, extraction_snapshot=result.to_snapshot()
        )
        await session.commit()
    return result


async def _log_advanced(ctx: StageContext, result: ExtractionResult, page_count: int) -> None:
    ctx.log_stage(
        "extract",
        "completed",
        page_count=page_count,
        document_profile=result.document_profile.value,
        total_tables=result.total_table_blocks,
        total_images=result.total_image_blocks,
        extraction_engine=result.extraction_engine,
        extraction_confidence=result.extraction_confidence,
        extraction_duration_ms=result.duration_ms,
        extraction_warnings=len(result.warnings),
    )
    await ctx.recorder.emit_stage(
        stage="extract",
        stage_status="completed",
        outputs={
            "page_count": page_count,
            "document_profile": result.document_profile.value,
            "total_text_blocks": result.total_text_blocks,
            "total_table_blocks": result.total_table_blocks,
            "total_image_blocks": result.total_image_blocks,
            "extraction_engine": result.extraction_engine,
            "extraction_confidence": result.extraction_confidence,
            "extraction_duration_ms": result.duration_ms,
            "warnings": result.warnings[:5],
        },
    )


def _legacy_sections(document: Any, content: bytes) -> list[Any]:
    if settings.ocr_enabled and document.file_type == "pdf":
        return list(extract_pdf_pages_native(content))
    try:
        return list(extract_text_sections(file_type=document.file_type, content=content))
    except ValueError as exc:
        raise _permanent("TEXT_EXTRACTION_FAILED", str(exc)) from exc


def _table_extras(result: ExtractionResult | None) -> dict[int, dict[str, Any]]:
    """Per page: table blocks and the first 300 characters of the text-block context."""
    if result is None:
        return {}
    extras: dict[int, dict[str, Any]] = {}
    for page in result.pages:
        if not page.table_blocks:
            continue
        context = " ".join(b.text.strip() for b in page.text_blocks if b.text.strip())
        extras[page.page_number] = {
            "tables": [table_to_dict(table) for table in page.table_blocks],
            "table_context": context[:300] if context else None,
        }
    return extras


async def run(ctx: StageContext) -> StageOutcome:
    ctx.current_stage = "extract"
    document = await load_document(ctx)
    ctx.log_stage("extract", "started")
    await ctx.recorder.emit_stage(
        stage="extract",
        stage_status="started",
        inputs={"bucket": document.storage_bucket, "object_key": document.storage_object_key},
    )
    content = _read_source(document)

    extraction: ExtractionResult | None = None
    if settings.feature_enable_advanced_pdf_extraction:
        extraction = await _advanced(ctx, document, content)
        sections = extraction.to_sections()
        await _log_advanced(ctx, extraction, len(sections))
    else:
        sections = _legacy_sections(document, content)
        ctx.log_stage("extract", "completed", page_count=len(sections))
        await ctx.recorder.emit_stage(
            stage="extract", stage_status="completed", outputs={"page_count": len(sections)}
        )

    ocr_applied = False
    if settings.ocr_enabled and document.file_type == "pdf":
        sections, ocr_applied = await _detect_and_ocr(ctx, document, content, sections)

    extras = _table_extras(extraction)
    page_parts = await write_pages(
        ctx,
        StageName.extract,
        [page_record(section, **extras.get(section.page_number, {})) for section in sections],
    )
    metrics: dict[str, Any] = {
        "page_count": len(sections),
        "artifact_parts": page_parts,
        "ocr_applied": ocr_applied,
        "advanced_extraction": extraction is not None,
    }
    if extraction is not None:
        metrics.update(
            document_profile=extraction.document_profile.value,
            total_text_blocks=extraction.total_text_blocks,
            total_table_blocks=extraction.total_table_blocks,
            total_image_blocks=extraction.total_image_blocks,
        )
    return StageOutcome(metrics=metrics)


async def _detect_and_ocr(
    ctx: StageContext, document: Any, content: bytes, sections: list[Any]
) -> tuple[list[Any], bool]:
    ctx.current_stage = "detect_ocr"
    await ctx.recorder.emit_stage(stage="detect_ocr", stage_status="started")
    detection = detect_ocr_need(sections, min_chars_per_page=settings.ocr_min_text_chars_per_page)
    await ctx.recorder.emit_stage(
        stage="detect_ocr",
        stage_status="completed",
        outputs={
            "requires_ocr": detection.requires_ocr,
            "mode": detection.mode,
            "page_count": detection.page_count,
            "native_text_pages": detection.native_text_pages,
            "ocr_candidate_pages": detection.ocr_candidate_pages,
            "reason": detection.reason,
        },
    )
    ctx.log_stage(
        "detect_ocr",
        "completed",
        ocr_required=detection.requires_ocr,
        ocr_mode=detection.mode,
    )
    if not detection.requires_ocr:
        return sections, False
    ctx.current_stage = "ocr"
    languages = resolve_ocr_tesseract_string(
        ocr_override=document.ocr_languages_override,
        document_language=document.language,
        system_default=settings.ocr_default_languages,
    )
    ocr_result = await run_ocr_step(
        ctx, document, content, detection, languages, ocr_fn=_ocr_function()
    )
    merged = merge_ocr_with_sections(
        sections, ocr_result, min_chars_per_page=settings.ocr_min_text_chars_per_page
    )
    if ocr_result.status == "failed":
        warnings = [p.warning for p in ocr_result.pages if p.warning]
        first_warning = warnings[0] if warnings else "unknown error"
        raise DocumentPipelinePermanentError(
            stage="ocr",
            code="OCR_FAILED",
            category="processing",
            message=f"OCR failed on all candidate pages: {first_warning}",
        )
    return list(merged), True


def _ocr_function() -> Any:
    """``run_ocr`` looked up at call time so tests can replace it on this module."""
    return run_ocr
