"""Short-session reads of the document and its chunk rows for the stages (R06-01)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.document import DocumentChunk
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.errors import document_not_found


async def load_document(ctx: StageContext) -> Any:
    """Read the document in its own session; the returned row is detached."""
    deps = ctx.deps
    async with deps.SessionLocal() as session:
        document = await deps.document_repository.get_document_by_id(
            session, document_id=ctx.document_id
        )
    if document is None:
        raise document_not_found(ctx.document_id_str)
    return document


def index_version(ctx: StageContext) -> str:
    return str(ctx.metrics["chunk"]["index_version"])


def embeddable_chunks_query(ctx: StageContext) -> Any:
    """Chunk rows that go into the vector store, in ``chunk_index`` order."""
    return (
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == ctx.document_id,
            DocumentChunk.index_version == index_version(ctx),
            DocumentChunk.qdrant_point_id.is_not(None),
        )
        .order_by(DocumentChunk.chunk_index)
    )
