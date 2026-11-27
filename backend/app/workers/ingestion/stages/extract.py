"""extract stage: streamed object read, text extraction, OCR detection and OCR (R06-01).

Pipeline-explorer stages ``extract``, ``detect_ocr``, ``ocr``. The stored object is
streamed to a temporary file (R06-02) and PDF and TXT are extracted from that file page by
page; each page's artifact part (text plus, for advanced extraction, that page's table
blocks and the first 300 characters of its text-block context) is written as soon as the
page is produced, so no list of all pages is held. When OCR may apply (PDF with
``OCR_ENABLED``) the pages below the native-text threshold are held back (their native
text is short by definition) and written into their reserved slots after OCR. Sessions
are short and never open during the object read, extraction, or OCR.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.domains.documents.extraction.extraction_service import stream_document
from app.domains.documents.extraction.models import (
    DocumentProfile,
    ExtractionResult,
    PageExtractionResult,
    page_to_section,
)
from app.domains.documents.services.ocr_detection import detect_ocr_need
from app.domains.documents.services.ocr_language_config import resolve_ocr_tesseract_string
from app.domains.documents.services.ocr_service import merge_ocr_with_sections, run_ocr
from app.domains.documents.services.text_extraction import (
    ExtractedSection,
    iter_pdf_sections,
    iter_text_sections,
)
from app.workers.base_task import PermanentTaskError, TransientTaskError
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.documents import load_document
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
)
from app.workers.ingestion.pages import PageWriter, page_record, table_to_dict
from app.workers.ingestion.stages.base import StageName, StageOutcome
from app.workers.ingestion.stages.ocr import run_ocr_step
from app.workers.ingestion.storage import download_to_tempfile


def _permanent(code: str, message: str, stage: str = "extract") -> DocumentPipelinePermanentError:
    return DocumentPipelinePermanentError(
        stage=stage, code=code, category="validation", message=message
    )


def _source_file(stack: ExitStack, document: Any) -> Path:
    try:
        return stack.enter_context(
            download_to_tempfile(document.storage_bucket, document.storage_object_key)
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


def _check_profile(profile: DocumentProfile | None) -> None:
    if profile == DocumentProfile.encrypted:
        raise _permanent("PDF_ENCRYPTED", "Document is password-protected and cannot be extracted")
    if profile == DocumentProfile.corrupted:
        raise _permanent("PDF_CORRUPTED", "Document appears to be corrupted or unreadable")


def _page_extras(page: PageExtractionResult) -> dict[str, Any]:
    """Table blocks and the first 300 characters of the page's text-block context."""
    if not page.table_blocks:
        return {}
    context = " ".join(b.text.strip() for b in page.text_blocks if b.text.strip())
    return {
        "tables": [table_to_dict(table) for table in page.table_blocks],
        "table_context": context[:300] if context else None,
    }


class _PageSink:
    """Writes pages as they come; holds back OCR candidates when OCR may apply."""

    def __init__(self, ctx: StageContext, *, defer_ocr_candidates: bool) -> None:
        self.writer = PageWriter(ctx, StageName.extract)
        self.defer = defer_ocr_candidates
        self.min_chars = settings.ocr_min_text_chars_per_page
        self.page_count = 0
        # Page number and char count only (no text), for OCR detection.
        self.stats: list[ExtractedSection] = []
        self.deferred: list[tuple[int, ExtractedSection, dict[str, Any]]] = []

    async def add(self, section: ExtractedSection, extras: dict[str, Any]) -> None:
        self.page_count += 1
        if not self.defer:
            await self.writer.add(page_record(section, **extras))
            return
        self.stats.append(ExtractedSection(section.page_number, "", section.char_count))
        if section.char_count < self.min_chars:
            self.deferred.append((self.writer.reserve(), section, extras))
        else:
            await self.writer.add(page_record(section, **extras))

    async def write_deferred(self, ocr_result: Any | None) -> None:
        for slot, section, extras in self.deferred:
            merged = section
            if ocr_result is not None:
                merged = merge_ocr_with_sections(
                    [section], ocr_result, min_chars_per_page=self.min_chars
                )[0]
            await self.writer.add(page_record(merged, **extras), slot=slot)
        self.deferred.clear()
        await self.writer.flush()


async def _advanced(
    ctx: StageContext, document: Any, path: Path, sink: _PageSink
) -> ExtractionResult:
    try:
        stream = _stream_function()(
            path,
            file_type=document.file_type,
            min_chars_per_page=settings.ocr_min_text_chars_per_page,
            max_pages=settings.pdf_extraction_max_pages,
            enable_table_extraction=settings.pdf_extraction_enable_tables,
            enable_image_extraction=settings.pdf_extraction_enable_images,
        )
    except ValueError as exc:
        raise _permanent("TEXT_EXTRACTION_FAILED", str(exc)) from exc
    try:
        _check_profile(stream.early_profile)
        try:
            for page in stream.pages():
                await sink.add(page_to_section(page), _page_extras(page))
        except ValueError as exc:
            raise _permanent("TEXT_EXTRACTION_FAILED", str(exc)) from exc
        result = stream.result()
    finally:
        stream.close()
    _check_profile(result.document_profile)

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


async def _legacy(document: Any, path: Path, sink: _PageSink) -> None:
    try:
        if settings.ocr_enabled and document.file_type == "pdf":
            sections = iter_pdf_sections(path)
        else:
            sections = iter_text_sections(file_type=document.file_type, content=path)
        for section in sections:
            await sink.add(section, {})
    except ValueError as exc:
        raise _permanent("TEXT_EXTRACTION_FAILED", str(exc)) from exc


async def run(ctx: StageContext) -> StageOutcome:
    ctx.current_stage = "extract"
    document = await load_document(ctx)
    ctx.log_stage("extract", "started")
    await ctx.recorder.emit_stage(
        stage="extract",
        stage_status="started",
        inputs={"bucket": document.storage_bucket, "object_key": document.storage_object_key},
    )
    ocr_possible = bool(settings.ocr_enabled and document.file_type == "pdf")
    sink = _PageSink(ctx, defer_ocr_candidates=ocr_possible)
    extraction: ExtractionResult | None = None
    ocr_result: Any | None = None
    with ExitStack() as stack:
        path = _source_file(stack, document)
        if settings.feature_enable_advanced_pdf_extraction:
            extraction = await _advanced(ctx, document, path, sink)
            await _log_advanced(ctx, extraction, sink.page_count)
        else:
            await _legacy(document, path, sink)
            ctx.log_stage("extract", "completed", page_count=sink.page_count)
            await ctx.recorder.emit_stage(
                stage="extract",
                stage_status="completed",
                outputs={"page_count": sink.page_count},
            )
        if ocr_possible:
            ocr_result = await _detect_and_ocr(ctx, document, path, sink.stats)
        await sink.write_deferred(ocr_result)

    metrics: dict[str, Any] = {
        "page_count": sink.page_count,
        "artifact_parts": sink.writer.parts_written,
        "ocr_applied": ocr_result is not None,
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
    ctx: StageContext, document: Any, path: Path, sections: list[ExtractedSection]
) -> Any | None:
    """OCR of the candidate pages; None when no page needs it. ``sections`` carry counts."""
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
        return None
    ctx.current_stage = "ocr"
    languages = resolve_ocr_tesseract_string(
        ocr_override=document.ocr_languages_override,
        document_language=document.language,
        system_default=settings.ocr_default_languages,
    )
    ocr_result = await run_ocr_step(
        ctx, document, path, detection, languages, ocr_fn=_ocr_function()
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
    return ocr_result


def _ocr_function() -> Any:
    """``run_ocr`` looked up at call time so tests can replace it on this module."""
    return run_ocr


def _stream_function() -> Any:
    """``stream_document`` looked up at call time so tests can replace it on this module."""
    return stream_document
