"""embed stage: embed and upsert the embeddable chunk rows batch by batch (R06-01).

Pipeline-explorer stages ``embed`` and ``index``. Batches are ``INGEST_EMBED_BATCH_CHUNKS``
rows in ``chunk_index`` order, each read in its own short session. A batch whose artifact
part exists was embedded and upserted by an earlier attempt of this run and is skipped, so
a redelivery only embeds the missing batches. Vectors are dropped after the upsert; the
part keeps token counts and cost for finalize.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.domains.documents.services.embedding_service import (
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from app.models.document import DocumentChunk
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.documents import embeddable_chunks_query, load_document
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
)
from app.workers.ingestion.stages.base import StageName, StageOutcome
from app.workers.ingestion.stages.embed_summary import log_embed_completed, summarize_parts


async def _read_batch(ctx: StageContext, batch: int, size: int) -> tuple[list[Any], dict]:
    """One batch of embeddable rows plus their parents' text, in one short session."""
    async with ctx.deps.SessionLocal() as session:
        rows = list(
            (
                await session.execute(embeddable_chunks_query(ctx).offset(batch * size).limit(size))
            ).scalars()
        )
        parent_ids = {row.parent_chunk_id for row in rows if row.parent_chunk_id is not None}
        parent_text: dict[UUID, str] = {}
        if parent_ids:
            parents = await session.execute(
                select(DocumentChunk.id, DocumentChunk.text).where(
                    DocumentChunk.id.in_(list(parent_ids))
                )
            )
            parent_text = {pid: str(text) for pid, text in parents}
    by_child = {
        row.id: parent_text[row.parent_chunk_id]
        for row in rows
        if row.parent_chunk_id is not None and row.parent_chunk_id in parent_text
    }
    return rows, by_child


async def _embed(ctx: StageContext, rows: list[Any]) -> Any:
    try:
        result = await ctx.deps.embedding_service.embed_chunks(chunks=rows)
    except PermanentEmbeddingError as exc:
        raise DocumentPipelinePermanentError(
            stage="embed",
            code="EMBEDDING_FAILED_PERMANENT",
            category="validation",
            message=str(exc),
        ) from exc
    except TransientEmbeddingError as exc:
        raise DocumentPipelineTransientError(
            stage="embed",
            code="EMBEDDING_FAILED_TRANSIENT",
            category="infrastructure",
            message=str(exc),
        ) from exc
    if len(result.vectors_by_chunk_id) != len(rows):
        raise DocumentPipelinePermanentError(
            stage="embed",
            code="EMBEDDING_INCOMPLETE",
            category="validation",
            message="embedding generation did not cover all chunks",
        )
    for chunk_id, vector in result.vectors_by_chunk_id.items():
        if len(vector) != settings.qdrant_vector_size:
            raise DocumentPipelinePermanentError(
                stage="embed",
                code="EMBEDDING_DIMENSION_MISMATCH",
                category="validation",
                message=(
                    f"embedding dimension mismatch for chunk {chunk_id}: "
                    f"expected {settings.qdrant_vector_size}, got {len(vector)}"
                ),
            )
    return result


async def _upsert(
    ctx: StageContext, document: Any, rows: list[Any], vectors: dict, parents: dict
) -> Any:
    chunk = ctx.metrics[StageName.chunk]
    kwargs: dict[str, Any] = {
        "organization_id": document.organization_id,
        "user_id": document.uploaded_by_user_id,
        "document_id": document.id,
        "filename": document.filename,
        "file_type": document.file_type,
        "chunks": rows,
        "vectors_by_chunk_id": vectors,
        "chunking_strategy": chunk["strategy_name"],
        "chunking_profile_version": chunk["strategy_version"],
        "parent_text_by_chunk_id": parents if parents else None,
    }
    if ctx.options.vector_collection is not None:
        kwargs["collection_name"] = ctx.options.vector_collection
    try:
        return await ctx.deps.qdrant_service.upsert_chunks(**kwargs)
    except ValueError as exc:
        raise DocumentPipelinePermanentError(
            stage="index",
            code="QDRANT_PAYLOAD_INVALID",
            category="validation",
            message=str(exc),
        ) from exc
    except Exception as exc:
        raise DocumentPipelineTransientError(
            stage="index",
            code="QDRANT_UPSERT_FAILED",
            category="infrastructure",
            message="qdrant upsert failed",
        ) from exc


def _part(result: Any, rows: list[Any], upsert: Any, size: int) -> dict[str, Any]:
    cost = getattr(result, "approximate_cost_usd", Decimal("0"))
    return {
        "batch_chunks": size,
        "chunk_count": len(rows),
        "batch_count": int(result.batch_count),
        "retry_count": int(result.retry_count),
        "input_tokens": int(result.input_tokens),
        "total_tokens": int(result.total_tokens),
        "latency_ms": int(result.latency_ms),
        "cost": str(cost),
        "upserted_count": int(upsert.upserted_count),
        "qdrant_batch_count": int(upsert.batch_count),
        "model_name": result.model_name,
        "index_version": getattr(result, "index_version", None),
        "provider_type": getattr(result, "provider_type", None),
        "vector_dimension": getattr(result, "vector_dimension", None),
    }


async def _completed_batches(ctx: StageContext, size: int) -> set[int]:
    """Parts of earlier attempts, discarded when they used another batch size.

    A changed ``INGEST_EMBED_BATCH_CHUNKS`` between deliveries would shift the batch
    boundaries; the run then embeds every batch again (the upserts replace the same point
    ids) rather than skip rows or count tokens twice.
    """
    done = await ctx.store.artifact_parts(StageName.embed)
    if not done:
        return done
    async for part in ctx.store.iter_artifacts(StageName.embed):
        if int(part.get("batch_chunks") or 0) != size:
            await ctx.store.write_artifacts(StageName.embed, {}, replace_stage=True)
            return set()
    return done


async def run(ctx: StageContext) -> StageOutcome:
    ctx.current_stage = "embed"
    document = await load_document(ctx)
    ctx.log_stage("embed", "started")
    await ctx.recorder.emit_stage(
        stage="embed",
        stage_status="started",
        config={"embedding_model": settings.openai_embedding_model},
    )
    size = settings.ingest_embed_batch_chunks
    total = int(ctx.metrics[StageName.chunk]["embeddable_count"])
    batches = math.ceil(total / size)
    done = await _completed_batches(ctx, size)
    for batch in range(batches):
        if batch in done:
            continue
        rows, parents = await _read_batch(ctx, batch, size)
        ctx.current_stage = "embed"
        result = await _embed(ctx, rows)
        ctx.current_stage = "index"
        upsert = await _upsert(ctx, document, rows, result.vectors_by_chunk_id, parents)
        part = _part(result, rows, upsert, size)
        del result, rows, parents
        await ctx.store.write_artifacts(StageName.embed, {batch: part}, replace_stage=False)
        await ctx.store.heartbeat(StageName.embed)

    summary = await summarize_parts(ctx)
    await log_embed_completed(ctx, summary)
    return StageOutcome(metrics={**summary, "artifact_parts": batches})
