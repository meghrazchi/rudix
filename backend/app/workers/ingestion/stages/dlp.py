"""dlp stage: data-loss-prevention scan of the cleaned text (R06-01).

Never persists matched content. ``quarantine`` and ``reject`` move the document to a
terminal security status (also during evaluation re-ingest, as before) and fail the run;
``warn`` records the scan result when document state is persisted.
"""

from __future__ import annotations

from app.core.config import settings
from app.domains.documents.services.dlp_service import scan_text_for_dlp
from app.models.enums import DocumentStatus
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.errors import DocumentPipelinePermanentError
from app.workers.ingestion.pages import read_pages
from app.workers.ingestion.stages.base import StageName, StageOutcome


async def run(ctx: StageContext) -> StageOutcome:
    if not settings.dlp_enabled:
        return StageOutcome(metrics={"enabled": False})
    ctx.current_stage = "dlp"
    await ctx.recorder.emit_stage(
        stage="dlp",
        stage_status="started",
        config={"action": settings.dlp_action, "min_findings": settings.dlp_min_findings},
    )
    pages = await read_pages(ctx, StageName.clean_detect)
    full_text = "\n".join(str(page["text"]) for page in pages if page["text"])
    result = scan_text_for_dlp(
        full_text,
        enabled=True,
        action=settings.dlp_action,  # type: ignore[arg-type]
        min_findings=settings.dlp_min_findings,
    )
    del full_text, pages
    categories = [finding.category for finding in result.findings]
    ctx.log_stage(
        "dlp",
        "completed",
        dlp_action=result.action,
        dlp_total_findings=result.total_findings,
    )
    await ctx.recorder.emit_stage(
        stage="dlp",
        stage_status="completed",
        outputs={
            "action": result.action,
            "total_findings": result.total_findings,
            "categories": categories,
        },
    )
    deps = ctx.deps
    if result.action in ("quarantine", "reject"):
        terminal_status = (
            DocumentStatus.quarantined.value
            if result.action == "quarantine"
            else DocumentStatus.blocked.value
        )
        async with deps.SessionLocal() as session:
            await deps.document_repository.update_document_dlp_result(
                session,
                document_id=ctx.document_id,
                status=terminal_status,
                dlp_scan_result=result.to_dict(),
                error_message=f"DLP policy action: {result.action}",
            )
            await session.commit()
        await deps.record_worker_audit_async(
            action=f"document.processing.dlp_{result.action}",
            resource_type="document",
            resource_id=ctx.document_id_str,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            request_id=ctx.request_id,
            metadata={
                "status": terminal_status,
                "total_findings": result.total_findings,
                "categories": categories,
            },
        )
        await ctx.recorder.finalize_run(
            status="failed",
            outputs={"final_status": terminal_status},
            error_message=f"DLP scan blocked document: {result.action}",
        )
        raise DocumentPipelinePermanentError(
            stage="dlp",
            code="DLP_POLICY_BLOCKED",
            category="security",
            message=f"Document blocked by DLP policy (action: {result.action})",
        )
    if result.action == "warn" and ctx.options.persist_document_state:
        async with deps.SessionLocal() as session:
            await deps.document_repository.update_document_dlp_result(
                session,
                document_id=ctx.document_id,
                status=DocumentStatus.processing.value,
                dlp_scan_result=result.to_dict(),
            )
            await session.commit()
    return StageOutcome(
        metrics={"enabled": True, "action": result.action, "total_findings": result.total_findings}
    )
