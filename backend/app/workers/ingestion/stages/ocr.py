"""OCR step of the extract stage, with OCR quality persistence (F299; R06-01)."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.errors import DocumentPipelinePermanentError


async def run_ocr_step(
    ctx: StageContext,
    document: Any,
    content: bytes,
    detection: Any,
    languages: str,
    *,
    ocr_fn: Any,
) -> Any:
    await ctx.recorder.emit_stage(
        stage="ocr",
        stage_status="started",
        config={
            "languages": languages,
            "dpi": settings.ocr_image_dpi,
            "max_pages": settings.ocr_max_pages,
            "page_timeout_seconds": settings.ocr_page_timeout_seconds,
            "language_source": (
                "override"
                if document.ocr_languages_override
                else ("document_language" if document.language else "system_default")
            ),
        },
    )
    try:
        result = ocr_fn(
            content,
            detection.ocr_candidate_pages,
            languages=languages,
            dpi=settings.ocr_image_dpi,
            page_timeout_seconds=settings.ocr_page_timeout_seconds,
            max_pages=settings.ocr_max_pages,
        )
    except RuntimeError as exc:
        raise DocumentPipelinePermanentError(
            stage="ocr",
            code="OCR_DEPENDENCIES_MISSING",
            category="infrastructure",
            message=str(exc),
        ) from exc

    completed = sum(1 for p in result.pages if p.status == "completed")
    failed = sum(1 for p in result.pages if p.status == "failed")
    stage_status = "failed" if result.status == "failed" else "completed"
    warnings = [p.warning for p in result.pages if p.warning]
    snapshot = {
        "status": result.status,
        "mode": detection.mode,
        "languages": result.languages,
        "effective_languages_string": languages,
        "pages_processed": len(result.pages),
        "pages_completed": completed,
        "pages_failed": failed,
        "duration_ms": result.duration_ms,
        "avg_confidence": result.avg_confidence,
        "page_confidences": [
            {"page_number": p.page_number, "status": p.status, "confidence": p.confidence}
            for p in result.pages
        ],
        "warnings": warnings,
    }
    await ctx.recorder.emit_stage(
        stage="ocr",
        stage_status=stage_status,
        outputs={
            "status": result.status,
            "mode": detection.mode,
            "languages": result.languages,
            "pages_processed": len(result.pages),
            "pages_completed": completed,
            "pages_failed": failed,
            "duration_ms": result.duration_ms,
            "avg_confidence": result.avg_confidence,
            "warnings": warnings,
        },
    )
    ctx.log_stage(
        "ocr",
        stage_status,
        ocr_status=result.status,
        ocr_pages_processed=len(result.pages),
        ocr_duration_ms=result.duration_ms,
        ocr_avg_confidence=result.avg_confidence,
        ocr_languages=result.languages,
    )
    await _persist_quality(ctx, document, result, snapshot)
    return result


async def _persist_quality(
    ctx: StageContext, document: Any, result: Any, snapshot: dict[str, Any]
) -> None:
    deps = ctx.deps
    quality_status = deps.ocr_quality_service.classify(
        avg_confidence=result.avg_confidence,
        ocr_status=result.status,
        ocr_applied=True,
        file_type=document.file_type,
    )
    async with deps.SessionLocal() as session:
        await deps.document_repository.update_document_ocr_quality(
            session,
            document_id=ctx.document_id,
            ocr_quality_snapshot=snapshot,
            ocr_quality_status=quality_status,
            ocr_avg_confidence=result.avg_confidence,
        )
        # Per-page OCR confidence for retrieval downranking.
        confidences = {
            p.page_number: p.confidence
            for p in result.pages
            if p.status == "completed" and p.confidence is not None
        }
        if confidences:
            await deps.document_repository.update_document_pages_ocr_confidence_bulk(
                session, document_id=ctx.document_id, page_confidences=confidences
            )
        await session.commit()
    deps.log_document_event(
        event="document.ocr_quality.classified",
        document_id=ctx.document_id_str,
        organization_id=ctx.organization_id,
        ocr_quality_status=quality_status,
        ocr_avg_confidence=result.avg_confidence,
    )
