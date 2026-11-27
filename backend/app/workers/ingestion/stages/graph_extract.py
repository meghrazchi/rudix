"""graph_extract stage: inline graph extraction after chunking, before embedding (R06-01).

Runs only when document state is persisted (evaluation re-ingest must not replace the
document's production graph facts with evidence pointing at eval chunks). The text chunk
rows the chunk stage committed are read in a short session; no session is open while the
extraction provider or Neo4j runs. ``ENTITY_EXTRACTION_STRICT_MODE`` still fails the run.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.models.document import DocumentChunk
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.documents import index_version, load_document
from app.workers.ingestion.stages.base import StageOutcome


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
    return StageOutcome(
        metrics={
            "entity_count": int(result.get("entity_count", 0)),
            "relation_count": int(result.get("relation_count", 0)),
        }
    )
