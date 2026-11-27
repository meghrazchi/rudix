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
from app.workers.ingestion.recorder import PIPELINE_RUN_KEY, PipelineRunRecorder
from app.workers.ingestion.runner import run_inline
from app.workers.ingestion.stages import StageName, build_stages
from app.workers.ingestion.stages.clean_detect import cleaning_stats_from_metrics
from app.workers.ingestion.stages.embed_summary import embedding_result
from app.workers.ingestion.stages.finalize import after_commit, refinalize
from app.workers.ingestion.store import COMPLETED, DbStageStore, MemoryStageStore, StageStore

PipelineResult = tuple[int, int, TextCleaningStats, EmbeddingResult]

# Stages up to and including finalize; graph_extract runs after (R06-01 part 2).
PRE_FINALIZE = frozenset(name for name in StageName if name != StageName.graph_extract)


def result_from_metrics(metrics: dict[str, dict[str, Any]]) -> PipelineResult:
    return (
        int(metrics[StageName.clean_detect]["page_count"]),
        int(metrics[StageName.chunk]["chunk_count"]),
        cleaning_stats_from_metrics(metrics[StageName.clean_detect]),
        embedding_result(metrics[StageName.embed]),
    )


def recorder_inputs(document: Any, options: IngestionOptions, request_id: str | None) -> dict:
    svc = options.chunking_service
    return {
        "pipeline_type": options.pipeline_type,
        "inputs": {
            "request_id": request_id,
            "document_id": str(document.id),
            "filename": document.filename,
            "file_type": document.file_type,
        },
        "config": {
            "index_version": getattr(svc, "index_version", settings.document_index_version),
            "embedding_model": settings.openai_embedding_model,
            "qdrant_collection": options.vector_collection or settings.qdrant_collection,
        },
    }


async def open_recorder(
    document: Any,
    *,
    options: IngestionOptions,
    request_id: str | None,
    organization_id: str,
    user_id: str,
    records: dict[str, Any],
) -> PipelineRunRecorder:
    """The run's pipeline-explorer recorder: resumed from the extract row, else new."""
    extract_row = records.get(StageName.extract)
    existing = extract_row.metrics.get(PIPELINE_RUN_KEY) if extract_row is not None else None
    return await PipelineRunRecorder.open_for_run(
        existing,
        document_id=str(document.id),
        organization_id=organization_id,
        user_id=user_id,
        organization_uuid=document.organization_id,
        document_uuid=document.id,
        **recorder_inputs(document, options, request_id),
    )


def make_store(deps: Any, document: Any, options: IngestionOptions, run_id: str) -> StageStore:
    if not options.persist_document_state:
        return MemoryStageStore(run_id=run_id)
    return DbStageStore(
        deps.SessionLocal,
        organization_id=document.organization_id,
        document_id=document.id,
        run_id=run_id,
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
    resolved_run_id = run_id or f"adhoc-{uuid4().hex}"
    store = make_store(deps, document, options, resolved_run_id)
    resolved_org = organization_id or str(document.organization_id)
    resolved_user = user_id or str(document.uploaded_by_user_id)
    records = await store.load()
    recorder = await open_recorder(
        document,
        options=options,
        request_id=request_id,
        organization_id=resolved_org,
        user_id=resolved_user,
        records=records,
    )
    ctx = StageContext(
        document_id=document.id,
        organization_id=resolved_org,
        user_id=resolved_user,
        request_id=request_id,
        run_id=resolved_run_id,
        claim_token=claim_token,
        options=options,
        deps=deps,
        recorder=recorder,
        store=store,
    )
    try:
        finalize = records.get(StageName.finalize)
        stages = build_stages(options)
        if finalize is not None and finalize.status == COMPLETED:
            # Redelivery of a run that already committed: restore ``indexed`` if a re-claim
            # moved the document back to processing; never a second usage event. Stages
            # after finalize (graph) still run when they did not finish.
            await _resume_completed(ctx, records)
            after = [stage for stage in stages if stage.name not in PRE_FINALIZE]
            if after:
                await run_inline(ctx, after)
        else:
            await run_inline(ctx, stages)
    except Exception as exc:
        await _record_failure(ctx, exc, organization_id=organization_id, user_id=user_id)
        raise
    return result_from_metrics(ctx.metrics)


async def run_after_finalize(
    document_id: str,
    *,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    options: IngestionOptions,
    run_id: str,
    claim_token: str | None,
) -> None:
    """Run the stages after ``finalize`` (graph) of a committed inline run that stopped
    before them; completed ones are skipped (their ``on_skip`` restores the graph status).
    """
    deps = current_deps()
    async with deps.SessionLocal() as session:
        document = await deps.document_repository.get_document_by_id(
            session, document_id=parse_document_id(document_id)
        )
    after = [stage for stage in build_stages(options) if stage.name not in PRE_FINALIZE]
    if document is None or not after:
        return
    if options.chunking_service is None:
        options = replace(options, chunking_service=deps.chunking_service)
    store = make_store(deps, document, options, run_id)
    resolved_org = organization_id or str(document.organization_id)
    resolved_user = user_id or str(document.uploaded_by_user_id)
    records = await store.load()
    ctx = StageContext(
        document_id=document.id,
        organization_id=resolved_org,
        user_id=resolved_user,
        request_id=request_id,
        run_id=run_id,
        claim_token=claim_token,
        options=options,
        deps=deps,
        recorder=await open_recorder(
            document,
            options=options,
            request_id=request_id,
            organization_id=resolved_org,
            user_id=resolved_user,
            records=records,
        ),
        store=store,
    )
    await run_inline(ctx, after)


async def _resume_completed(ctx: StageContext, records: dict[str, Any]) -> None:
    for name, record in records.items():
        ctx.metrics[name] = dict(record.metrics)
    for stage in build_stages(ctx.options):
        if stage.name not in PRE_FINALIZE:
            continue
        record = records.get(stage.name)
        if stage.on_skip is not None and record is not None and record.status == COMPLETED:
            await stage.on_skip(ctx, dict(record.metrics))
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
        # Compared in SQL against the stored value: both sides use the database clock.
        finished_at = select(stage.finished_at).where(stage.id == finalize.id).scalar_subquery()
        reported = (
            await session.execute(
                select(AuditLog.id)
                .where(
                    AuditLog.organization_id == finalize.organization_id,
                    AuditLog.resource_id == parsed,
                    AuditLog.action == audit_action,
                    AuditLog.created_at >= finished_at,
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
