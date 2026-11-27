"""graph_extract stage: graph extraction after ``finalize`` (R06-01; moved in part 2).

Runs only when document state is persisted (evaluation re-ingest must not replace the
document's production graph facts with evidence pointing at eval chunks). The text chunk
rows the chunk stage committed are read in a short session; no session is open while the
extraction provider or Neo4j runs.

The document is already ``indexed`` when this stage runs, and a graph failure never fails
it: any error (including ``ENTITY_EXTRACTION_STRICT_MODE`` and
``RELATION_EXTRACTION_STRICT_MODE`` failures) sets ``graph_extraction_status=failed``, and
the stage completes with ``graph_status=failed`` and the error code in its metrics.

The task body marks the graph status ``pending`` (clearing the graph run id) on every
delivery. The stage keeps the graph status and run id it left in its metrics, and
``on_skip`` writes them back when a redelivery of the same run skips the finished stage.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.document_errors import details_from_exception
from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk
from app.models.enums import GraphExtractionStatus
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.documents import index_version, load_document
from app.workers.ingestion.stages.base import StageOutcome

logger = get_logger("worker.ingestion")


async def _graph_state(ctx: StageContext) -> tuple[str | None, str | None]:
    async with ctx.deps.SessionLocal() as session:
        row = (
            await session.execute(
                select(Document.graph_extraction_status, Document.graph_extraction_run_id).where(
                    Document.id == ctx.document_id
                )
            )
        ).first()
    if row is None:
        return None, None
    status, run_id = row
    return (str(status) if status is not None else None), (
        str(run_id) if run_id is not None else None
    )


async def on_skip(ctx: StageContext, metrics: dict[str, Any]) -> None:
    """Restore the graph status this run reached (the task body reset it to pending)."""
    status = metrics.get("graph_status")
    if not status:
        return
    run_id = metrics.get("graph_run_id")
    await ctx.deps.update_document_graph_status_async(
        ctx.document_id, status=str(status), run_id=UUID(str(run_id)) if run_id else None
    )


async def run(ctx: StageContext) -> StageOutcome:
    document = await load_document(ctx)
    async with ctx.deps.SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    DocumentChunk.chunk_index,
                    DocumentChunk.id,
                    DocumentChunk.text,
                    DocumentChunk.page_number,
                )
                .where(
                    DocumentChunk.document_id == ctx.document_id,
                    DocumentChunk.index_version == index_version(ctx),
                    DocumentChunk.chunk_type == "text",
                )
                .order_by(DocumentChunk.chunk_index)
            )
        ).all()
    chunk_pairs = [(int(index), str(text)) for index, _, text, _ in rows if str(text).strip()]
    chunk_id_by_index: dict[int, UUID | None] = {int(index): cid for index, cid, _, _ in rows}
    page_by_index: dict[int, int | None] = {int(index): page for index, _, _, page in rows}
    try:
        result = await ctx.deps.run_document_graph_extraction_async(
            document,
            request_id=ctx.request_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            pipeline_type=ctx.options.pipeline_type,
            chunk_pairs=chunk_pairs,
            chunk_id_by_index=chunk_id_by_index,
            page_by_index=page_by_index,
            pipeline_recorder=ctx.recorder,
            clear_existing_facts=True,
        )
    except Exception as exc:
        return await _graph_failed(ctx, exc)
    graph_status, graph_run_id = await _graph_state(ctx)
    return StageOutcome(
        metrics={
            "entity_count": int(result.get("entity_count", 0)),
            "relation_count": int(result.get("relation_count", 0)),
            "graph_status": graph_status,
            "graph_run_id": graph_run_id,
        }
    )


async def _graph_failed(ctx: StageContext, exc: Exception) -> StageOutcome:
    """Record a graph failure on the graph status only; the document stays indexed."""
    details = details_from_exception(exc)
    code = str(details.get("code", type(exc).__name__))[:64]
    _, graph_run_id = await _graph_state(ctx)
    await ctx.deps.update_document_graph_status_async(
        ctx.document_id,
        status=GraphExtractionStatus.failed.value,
        run_id=UUID(graph_run_id) if graph_run_id else None,
    )
    await ctx.recorder.fail_stage_if_open(
        stage=str(details.get("stage", "extract_entities")),
        error_message=str(details.get("message", type(exc).__name__)),
        error_details=details,
    )
    ctx.log_stage("graph_extract", "failed", error_code=code)
    logger.warning(
        "ingestion.graph_extract.failed",
        document_id=ctx.document_id_str,
        organization_id=ctx.organization_id,
        run_id=ctx.run_id,
        error_code=code,
    )
    return StageOutcome(
        metrics={
            "entity_count": 0,
            "relation_count": 0,
            "graph_status": GraphExtractionStatus.failed.value,
            "graph_run_id": graph_run_id,
            "error_code": code,
        }
    )
