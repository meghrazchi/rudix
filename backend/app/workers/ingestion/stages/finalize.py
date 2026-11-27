"""finalize stage: the only writer of ``indexed`` and of the embedding usage event (R06-01).

One transaction writes the embedding metadata, moves the document to ``indexed`` only while
``processing_task_id`` still equals the run's claim token, records the
``document.embedding`` usage event with token sums from the embed batch parts, and marks
the finalize stage row completed. After the commit the pipeline run is finalized and this
run's artifacts plus other runs' rows of the document are deleted.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
)
from app.workers.ingestion.stages.base import StageName, StageOutcome
from app.workers.ingestion.stages.chunk_metrics import chunking_snapshot

logger = get_logger("worker.ingestion")


async def _claim_holder(ctx: StageContext, session: Any) -> str | None:
    stmt = select(Document.processing_task_id).where(Document.id == ctx.document_id)
    return (await session.execute(stmt.with_for_update())).scalar_one_or_none()


async def _write_document_state(ctx: StageContext, session: Any, embed: dict[str, Any]) -> Any:
    repository = ctx.deps.document_repository
    if ctx.claim_token is not None and await _claim_holder(ctx, session) != ctx.claim_token:
        raise DocumentPipelinePermanentError(
            stage="status",
            code="CLAIM_SUPERSEDED",
            category="processing",
            message=f"processing claim moved to another task: {ctx.document_id_str}",
        )
    await repository.update_document_embedding_metadata(
        session,
        document_id=ctx.document_id,
        embedding_provider_type=embed.get("provider_type"),
        embedding_vector_dimension=embed.get("vector_dimension"),
    )
    chunk = ctx.metrics[StageName.chunk]
    return await repository.update_document_status(
        session,
        document_id=ctx.document_id,
        status=DocumentStatus.indexed.value,
        error_message=None,
        page_count=int(ctx.metrics[StageName.clean_detect]["page_count"]),
        chunk_count=int(chunk["chunk_count"]) + int(chunk.get("table_chunk_count", 0)),
        chunking_strategy=chunk["strategy_name"],
        chunking_profile_version=chunk["strategy_version"],
        chunking_config_snapshot=chunking_snapshot(ctx, embed),
        clear_processing_claim=True,
    )


async def _record_usage(ctx: StageContext, session: Any, document: Any, embed: dict) -> None:
    await ctx.deps.usage_repository.create_usage_event(
        session,
        organization_id=document.organization_id,
        user_id=document.uploaded_by_user_id,
        event_type="document.embedding",
        model_name=embed["model_name"],
        input_tokens=embed["input_tokens"],
        output_tokens=None,
        cost_usd=Decimal(str(embed["cost"])),
        metadata={
            "document_id": str(document.id),
            "chunk_count": embed["chunk_count"],
            "batch_count": embed["batch_count"],
            "retry_count": embed["retry_count"],
            "index_version": embed["index_version"],
            "latency_ms": embed["latency_ms"],
            "total_tokens": embed["total_tokens"],
            "qdrant_upserted_count": embed["upserted_count"],
            "qdrant_batch_count": embed["qdrant_batch_count"],
        },
    )


async def run(ctx: StageContext) -> StageOutcome:
    ctx.current_stage = "status"
    embed = ctx.metrics[StageName.embed]
    options = ctx.options
    deps = ctx.deps
    metrics = {"persisted": options.persist_document_state}
    async with deps.SessionLocal() as session:
        try:
            document = await deps.document_repository.get_document_by_id(
                session, document_id=ctx.document_id
            )
            updated: Any = object()
            if options.persist_document_state:
                updated = await _write_document_state(ctx, session, embed)
            if options.record_usage_event and document is not None:
                await _record_usage(ctx, session, document, embed)
            if updated is not None:
                await ctx.store.mark_completed(StageName.finalize, metrics=metrics, session=session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    if updated is None:
        raise DocumentPipelineTransientError(
            stage="status",
            code="STATUS_INDEXED_UPDATE_FAILED",
            category="infrastructure",
            message=f"Unable to move document to indexed state: {ctx.document_id_str}",
        )
    await after_commit(ctx)
    return StageOutcome(metrics=metrics, marked=True)


async def refinalize(ctx: StageContext) -> None:
    """Restore ``indexed`` for a committed run whose document was claimed again.

    The usage event and the stage row were committed by the first finalize; only the
    document state is written again, and only while this run still holds the claim.
    """
    async with ctx.deps.SessionLocal() as session:
        try:
            updated = await _write_document_state(ctx, session, ctx.metrics[StageName.embed])
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    if updated is None:
        raise DocumentPipelineTransientError(
            stage="status",
            code="STATUS_INDEXED_UPDATE_FAILED",
            category="infrastructure",
            message=f"Unable to move document to indexed state: {ctx.document_id_str}",
        )


async def after_commit(ctx: StageContext) -> None:
    """Pipeline run completion and artifact cleanup; safe to repeat."""
    chunk = ctx.metrics[StageName.chunk]
    await ctx.recorder.finalize_run(
        status="completed",
        outputs={
            "document_status": (
                DocumentStatus.indexed.value
                if ctx.options.persist_document_state
                else "evaluation_indexed"
            ),
            "page_count": int(ctx.metrics[StageName.clean_detect]["page_count"]),
            "chunk_count": int(chunk["chunk_count"]),
            "index_version": chunk["index_version"],
        },
    )
    try:
        await ctx.store.delete_run_artifacts()
        await ctx.store.purge_other_runs()
    except Exception as exc:
        # The run is complete; leftover artifacts are removed by the next run or deletion.
        logger.warning(
            "ingestion.artifact_cleanup_failed",
            document_id=ctx.document_id_str,
            organization_id=ctx.organization_id,
            run_id=ctx.run_id,
            error_type=type(exc).__name__,
        )
