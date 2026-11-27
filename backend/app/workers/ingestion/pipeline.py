"""One document ingestion run: context, stages, failure telemetry, result (R06-01).

``extract_and_store`` backs ``document_tasks._extract_and_store_document_pages_async``. It
resolves the document in a short session, opens the pipeline-explorer run, and runs the
stages inline with a ``DbStageStore`` (``MemoryStageStore`` when document state is not
persisted). ``run_id`` is the claim's task id, so a redelivery or ``self.retry`` of the same
task resumes after the last completed stage.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.document_errors import details_from_exception
from app.domains.documents.services.embedding_service import EmbeddingResult
from app.domains.documents.services.text_normalization import TextCleaningStats
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import document_not_found, parse_document_id
from app.workers.ingestion.options import IngestionOptions
from app.workers.ingestion.recorder import PipelineRunRecorder
from app.workers.ingestion.runner import run_inline
from app.workers.ingestion.stages import StageName, build_stages
from app.workers.ingestion.stages.clean_detect import cleaning_stats_from_metrics
from app.workers.ingestion.stages.embed_summary import embedding_result
from app.workers.ingestion.stages.finalize import after_commit, refinalize
from app.workers.ingestion.store import COMPLETED, DbStageStore, MemoryStageStore, StageStore

PipelineResult = tuple[int, int, TextCleaningStats, EmbeddingResult]


def result_from_metrics(metrics: dict[str, dict[str, Any]]) -> PipelineResult:
    return (
        int(metrics[StageName.clean_detect]["page_count"]),
        int(metrics[StageName.chunk]["chunk_count"]),
        cleaning_stats_from_metrics(metrics[StageName.clean_detect]),
        embedding_result(metrics[StageName.embed]),
    )


async def extract_and_store(
    document_id: str,
    *,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    options: IngestionOptions,
    run_id: str | None = None,
    claim_token: str | None = None,
) -> PipelineResult:
    parsed_document_id = parse_document_id(document_id)
    deps = current_deps()
    async with deps.SessionLocal() as session:
        document = await deps.document_repository.get_document_by_id(
            session, document_id=parsed_document_id
        )
    if document is None:
        raise document_not_found(document_id)

    if options.chunking_service is None:
        options = replace(options, chunking_service=deps.chunking_service)
    svc = options.chunking_service
    recorder = await PipelineRunRecorder.create(
        document_id=document_id,
        organization_id=organization_id or str(document.organization_id),
        user_id=user_id or str(document.uploaded_by_user_id),
        organization_uuid=document.organization_id,
        document_uuid=document.id,
        pipeline_type=options.pipeline_type,
        inputs={
            "request_id": request_id,
            "document_id": str(document.id),
            "filename": document.filename,
            "file_type": document.file_type,
        },
        config={
            "index_version": getattr(svc, "index_version", settings.document_index_version),
            "embedding_model": settings.openai_embedding_model,
            "qdrant_collection": options.vector_collection or settings.qdrant_collection,
        },
    )
    resolved_run_id = run_id or f"adhoc-{uuid4().hex}"
    store: StageStore = (
        DbStageStore(
            deps.SessionLocal,
            organization_id=document.organization_id,
            document_id=document.id,
            run_id=resolved_run_id,
        )
        if options.persist_document_state
        else MemoryStageStore(run_id=resolved_run_id)
    )
    ctx = StageContext(
        document_id=document.id,
        organization_id=organization_id or str(document.organization_id),
        user_id=user_id or str(document.uploaded_by_user_id),
        request_id=request_id,
        run_id=resolved_run_id,
        claim_token=claim_token,
        options=options,
        deps=deps,
        recorder=recorder,
        store=store,
    )
    try:
        records = await store.load()
        finalize = records.get(StageName.finalize)
        if finalize is not None and finalize.status == COMPLETED:
            # Redelivery of a run that already committed: restore ``indexed`` if a re-claim
            # moved the document back to processing; never a second usage event.
            await _resume_completed(ctx, records)
        else:
            await run_inline(ctx, build_stages(options))
    except Exception as exc:
        await _record_failure(ctx, exc, organization_id=organization_id, user_id=user_id)
        raise
    return result_from_metrics(ctx.metrics)


async def _resume_completed(ctx: StageContext, records: dict[str, Any]) -> None:
    for name, record in records.items():
        ctx.metrics[name] = dict(record.metrics)
    if ctx.options.persist_document_state and ctx.claim_token is not None:
        await refinalize(ctx)
    await after_commit(ctx)


async def _record_failure(
    ctx: StageContext, exc: Exception, *, organization_id: str | None, user_id: str | None
) -> None:
    details = details_from_exception(exc)
    failing_stage = details.get("stage", "unknown")
    if failing_stage == "unknown":
        failing_stage = ctx.current_stage
    if failing_stage == "chunk":
        ctx.deps.log_chunking_event(
            event="document.chunking.failed",
            document_id=ctx.document_id_str,
            organization_id=organization_id,
            user_id=user_id,
            error_code=details.get("code", "UNKNOWN"),
            error_message=details.get("message", str(exc)),
        )
    await ctx.recorder.fail_stage_if_open(
        stage=failing_stage,
        error_message=details.get("message", str(exc)),
        error_details=details,
    )
    await ctx.recorder.finalize_run(
        status="failed",
        error_message=details.get("message", str(exc)),
        error_details=details,
    )


async def completed_run_metrics(
    document_id: str, *, run_id: str, audit_action: str
) -> dict[str, dict[str, Any]] | None:
    """Metrics of a run whose finalize committed but whose completion was not reported.

    Used when a redelivered ``documents.process`` finds its document already ``indexed``:
    the worker died after the finalize commit and before the completion audit.
    """
    from sqlalchemy import select

    from app.models.document_processing import DocumentProcessingStage
    from app.models.usage import AuditLog

    try:
        parsed = parse_document_id(document_id)
    except Exception:
        return None
    deps = current_deps()
    stage = DocumentProcessingStage
    async with deps.SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(stage).where(stage.document_id == parsed, stage.run_id == run_id)
                )
            ).scalars()
        )
        by_name = {row.stage: row for row in rows if row.status == COMPLETED}
        finalize = by_name.get(StageName.finalize)
        if finalize is None or finalize.finished_at is None:
            return None
        reported = (
            await session.execute(
                select(AuditLog.id)
                .where(
                    AuditLog.organization_id == finalize.organization_id,
                    AuditLog.resource_id == parsed,
                    AuditLog.action == audit_action,
                    AuditLog.created_at >= finalize.finished_at,
                )
                .limit(1)
            )
        ).first()
    if reported is not None:
        return None
    store = DbStageStore(
        deps.SessionLocal,
        organization_id=finalize.organization_id,
        document_id=parsed,
        run_id=run_id,
    )
    await store.delete_run_artifacts()
    await store.purge_other_runs()
    return {name: dict(row.metrics or {}) for name, row in by_name.items()}
