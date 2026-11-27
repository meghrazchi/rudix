"""Bodies of ``documents.process`` and ``documents.reindex`` (moved from document_tasks, R06-01).

The claim, graph-pending mark, completion log, audit, and notification are unchanged.

``INGEST_PIPELINE_MODE=chain`` (default, R06-01 part 2): after the claim the task chooses
the run (``chain.resolve_run_id``: a new run per claim, or ``resume_run_id`` / a failed
job's run while unfinished) and dispatches the first incomplete stage; the stage tasks do
the rest and the finalize task reports the run. The task returns ``status=processing``.

``INGEST_PIPELINE_MODE=inline``: the stages run in this task with ``run_id = claim_token =
request.id`` (or ``resume_run_id``), so a retry or redelivery resumes after the last
completed stage. A redelivered ``documents.process`` whose run already committed (the
worker died between the finalize commit and the completion audit) runs the stages after
finalize that did not finish (graph) and reports that run instead of skipping it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.domains.documents.repositories.processing_claims import (
    PROCESS_SKIP_STATUSES,
    REINDEX_FORBIDDEN_STATUSES,
    ClaimOutcome,
)
from app.models.enums import DocumentStatus, GraphExtractionStatus
from app.workers.base_task import PermanentTaskError
from app.workers.ingestion.chain import (
    PROCESS_MODE,
    REINDEX_MODE,
    completed_stages,
    first_incomplete,
    resolve_run_id,
    stage_kwargs,
)
from app.workers.ingestion.deps import IngestionDeps, current_deps
from app.workers.ingestion.errors import parse_uuid
from app.workers.ingestion.options import IngestionOptions
from app.workers.ingestion.pipeline import (
    completed_run_metrics,
    result_from_metrics,
    run_after_finalize,
)


@dataclass(frozen=True)
class TaskMode:
    pipeline_type: str
    event_prefix: str
    audit_action: str
    reindex: bool


PROCESS = TaskMode("document.process", "document.processing", "document.process.completed", False)
REINDEX = TaskMode("document.reindex", "document.reindex", "document.reindex.completed", True)


def _claim(deps: IngestionDeps, mode: TaskMode, document_id: str, task_id: str, force: bool) -> Any:
    statuses: dict[str, Any] = (
        {"forbidden_statuses": REINDEX_FORBIDDEN_STATUSES}
        if mode.reindex
        else {"skip_statuses": PROCESS_SKIP_STATUSES}
    )
    try:
        claim = deps.claim_document_for_processing(
            document_id, task_id=task_id, force=force, **statuses
        )
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if claim.outcome == ClaimOutcome.not_found:
        raise PermanentTaskError(f"Document not found: {document_id}")
    return claim


def run_document_task(
    task: Any,
    document_id: str,
    *,
    mode: TaskMode,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    force: bool,
    chunking_profile_config: dict | None,
    resume_run_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, str | int | float]:
    deps = current_deps()
    # request.id survives Celery retries and acks_late redeliveries, so the owning task can
    # re-enter its own claim; root_id is shared by sibling tasks and must not be used.
    task_id = task.request.id or f"adhoc-{uuid4().hex}"
    claim = _claim(deps, mode, document_id, task_id, force)
    context = {
        "document_id": document_id,
        "request_id": request_id,
        "organization_id": organization_id,
        "user_id": user_id,
    }
    if claim.outcome == ClaimOutcome.held:
        if mode.reindex and claim.current_status == DocumentStatus.deleted.value:
            raise PermanentTaskError(f"Cannot reindex deleted document: {document_id}")
        if mode.reindex and claim.current_status == DocumentStatus.deleting.value:
            raise PermanentTaskError(f"Cannot reindex deleting document: {document_id}")
        if not mode.reindex and claim.current_status == DocumentStatus.indexed.value:
            metrics = deps.run(
                completed_run_metrics(document_id, run_id=task_id, audit_action=mode.audit_action)
            )
            if metrics is not None:
                if settings.ingest_pipeline_mode == "inline":
                    deps.run(
                        run_after_finalize(
                            document_id,
                            request_id=request_id,
                            organization_id=organization_id,
                            user_id=user_id,
                            options=IngestionOptions(pipeline_type=mode.pipeline_type),
                            run_id=task_id,
                            claim_token=None,
                        )
                    )
                return report(deps, mode, context, force, result_from_metrics(metrics))
        reason = "claim_held"
        if not mode.reindex and claim.current_status != DocumentStatus.processing.value:
            reason = "status_not_claimable"
        deps.log_document_event(
            event=f"{mode.event_prefix}.skipped",
            status_code=claim.current_status,
            reason=reason,
            processing_task_id=task_id,
            **context,
        )
        return {"document_id": document_id, "status": "skipped"}

    try:
        document_uuid = parse_uuid(document_id)
    except ValueError:
        document_uuid = None
    if document_uuid is not None:
        deps.run(
            deps.update_document_graph_status_async(
                document_uuid, status=GraphExtractionStatus.pending.value, run_id=None
            )
        )
    started: dict[str, Any] = {"force": force} if mode.reindex else {"processing_task_id": task_id}
    deps.log_document_event(
        event=f"{mode.event_prefix}.started",
        status_code=DocumentStatus.processing.value,
        **started,
        **context,
    )
    try:
        service = deps.make_chunking_service(chunking_profile_config)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid chunking_profile_config: {exc}") from exc

    chain = settings.ingest_pipeline_mode == "chain"
    run_id, resumed = deps.run(
        resolve_run_id(
            document_id,
            claim_token=task_id,
            resume_run_id=resume_run_id,
            job_id=job_id,
            organization_id=organization_id,
            chain=chain,
        )
    )
    profile_source = "custom_profile" if chunking_profile_config else "system_default"
    if chain:
        return _start_chain(
            deps,
            mode,
            context,
            run_id=run_id,
            claim_token=task_id,
            resumed=resumed,
            chunking_profile_config=chunking_profile_config,
            profile_source=profile_source,
            force=force,
        )

    result = deps.run(
        deps.extract_and_store_document_pages_async(
            document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            pipeline_type=mode.pipeline_type,
            chunking_service=service,
            profile_source=profile_source,
            run_id=run_id,
            claim_token=task_id,
        )
    )
    return report(deps, mode, context, force, result)


def _start_chain(
    deps: IngestionDeps,
    mode: TaskMode,
    context: dict[str, Any],
    *,
    run_id: str,
    claim_token: str,
    resumed: bool,
    chunking_profile_config: dict | None,
    profile_source: str,
    force: bool,
) -> dict[str, str | int | float]:
    """Dispatch the first stage of the run that is not completed yet."""
    from app.workers.ingestion.dispatch import dispatch_stage

    document_id = str(context["document_id"])
    done: set[str] = set()
    if resumed:
        done = deps.run(completed_stages(parse_uuid(document_id), run_id))
    stage = first_incomplete(done)
    deps.log_document_event(
        event=f"{mode.event_prefix}.dispatched",
        status_code=DocumentStatus.processing.value,
        run_id=run_id,
        resumed=resumed,
        stage=str(stage) if stage is not None else None,
        **context,
    )
    if stage is not None:
        dispatch_stage(
            stage,
            stage_kwargs(
                document_id=document_id,
                organization_id=context["organization_id"],
                user_id=context["user_id"],
                request_id=context["request_id"],
                run_id=run_id,
                claim_token=claim_token,
                chunking_profile_config=chunking_profile_config,
                profile_source=profile_source,
                mode=REINDEX_MODE if mode.reindex else PROCESS_MODE,
                force=force,
            ),
        )
    return {
        "document_id": document_id,
        "status": DocumentStatus.processing.value,
        "run_id": run_id,
        "stage": str(stage) if stage is not None else "completed",
    }


def report(
    deps: IngestionDeps,
    mode: TaskMode,
    context: dict[str, Any],
    force: bool,
    result: tuple[int, int, Any, Any],
) -> dict[str, str | int | float]:
    page_count, chunk_count, cleaning_stats, embedding = result
    document_id = context["document_id"]
    forced: dict[str, Any] = {"force": force} if mode.reindex else {}
    embedding_fields = {
        "embedding_batch_count": embedding.batch_count,
        "embedding_retry_count": embedding.retry_count,
        "embedding_input_tokens": embedding.input_tokens,
        "embedding_total_tokens": embedding.total_tokens,
        "embedding_latency_ms": embedding.latency_ms,
        "embedding_cost_usd": float(embedding.approximate_cost_usd),
    }
    deps.log_document_event(
        event=f"{mode.event_prefix}.completed",
        status_code=DocumentStatus.indexed.value,
        **forced,
        page_count=page_count,
        chunk_count=chunk_count,
        index_version=settings.document_index_version,
        **embedding_fields,
        qdrant_collection=settings.qdrant_collection,
        **cleaning_stats.as_log_fields(),
        **context,
    )
    deps.record_worker_audit(
        action=mode.audit_action,
        resource_type="document",
        resource_id=document_id,
        organization_id=context["organization_id"],
        user_id=context["user_id"],
        request_id=context["request_id"],
        metadata={
            "status": DocumentStatus.indexed.value,
            "page_count": page_count,
            "chunk_count": chunk_count,
            **forced,
        },
    )
    if not mode.reindex:
        from app.workers.notification_helper import emit_notification

        emit_notification(
            organization_id=context["organization_id"],
            user_id=context["user_id"],
            event_type="upload_indexed",
            severity="info",
            title="Document indexed",
            message=f"{page_count} page(s), {chunk_count} chunk(s) ready for search.",
            href=f"/documents?highlight={document_id}",
            source_id=document_id,
        )
    return {
        "document_id": document_id,
        "status": DocumentStatus.indexed.value,
        "page_count": page_count,
        "chunk_count": chunk_count,
        "index_version": settings.document_index_version,
        **embedding_fields,
        "cleaning_pages_modified": cleaning_stats.pages_modified,
    }
