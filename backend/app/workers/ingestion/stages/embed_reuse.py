"""Vector reuse before embedding (R06-06).

The vector index is the cache: before a batch is sent to the provider, points of the same
organisation and embedding model with the same ``chunk_hash`` are looked up with one
scroll, and their vectors are reused. Only the misses are embedded. A failed lookup never
fails ingestion; the batch is then embedded as before. Reused chunks cost no tokens.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_embedding_cache
from app.workers.ingestion.context import StageContext

logger = get_logger("worker.ingestion")


@dataclass(frozen=True)
class ReusedOnlyResult:
    """Embedding summary of a batch whose every vector was reused (no provider call)."""

    model_name: str
    index_version: str | None
    provider_type: str | None
    vector_dimension: int
    batch_count: int = 0
    retry_count: int = 0
    input_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    approximate_cost_usd: Decimal = Decimal("0")


def embedding_model_of(ctx: StageContext) -> str:
    service = ctx.deps.embedding_service
    return str(getattr(service, "model_name", None) or settings.openai_embedding_model).strip()


async def _lookup(ctx: StageContext, document: Any, model: str, rows: list[Any]) -> dict:
    hashes = [row.chunk_hash for row in rows if row.chunk_hash and row.embedding_model == model]
    if not hashes:
        return {}
    kwargs: dict[str, Any] = {
        "organization_id": document.organization_id,
        "embedding_model": model,
        "chunk_hashes": hashes,
    }
    if ctx.options.vector_collection is not None:
        kwargs["collection_name"] = ctx.options.vector_collection
    try:
        return dict(await ctx.deps.qdrant_service.find_reusable_vectors(**kwargs))
    except Exception as exc:
        logger.warning(
            "ingestion.embedding_reuse_lookup_failed",
            document_id=ctx.document_id_str,
            organization_id=ctx.organization_id,
            run_id=ctx.run_id,
            error_type=type(exc).__name__,
        )
        return {}


async def embed_with_reuse(
    ctx: StageContext,
    document: Any,
    rows: list[Any],
    embed: Callable[[StageContext, list[Any]], Awaitable[Any]],
) -> tuple[dict[UUID, list[float]], Any, int]:
    """Vectors for ``rows``, the embedding summary, and the number of reused vectors."""
    model = embedding_model_of(ctx)
    found = await _lookup(ctx, document, model, rows)
    reused: dict[UUID, list[float]] = {}
    for row in rows:
        vector = found.get(row.chunk_hash) if row.embedding_model == model else None
        if vector is not None and len(vector) == settings.qdrant_vector_size:
            reused[row.id] = vector
    misses = [row for row in rows if row.id not in reused]
    record_embedding_cache(len(reused), len(misses))
    if not misses:
        service = ctx.deps.embedding_service
        first = next(iter(reused.values()))
        summary: Any = ReusedOnlyResult(
            model_name=model,
            index_version=getattr(service, "index_version", None) or rows[0].index_version,
            provider_type=getattr(service, "provider_type", None),
            vector_dimension=len(first),
        )
        return reused, summary, len(reused)
    result = await embed(ctx, misses)
    return {**reused, **result.vectors_by_chunk_id}, result, len(reused)
