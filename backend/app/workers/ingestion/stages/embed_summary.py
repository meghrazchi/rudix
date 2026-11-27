"""Aggregation of embed batch parts for logs, finalize, and the facade result (R06-01)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.domains.documents.services.embedding_service import EmbeddingResult
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.stages.base import StageName

_SUMMED = (
    "chunk_count",
    "batch_count",
    "retry_count",
    "input_tokens",
    "total_tokens",
    "latency_ms",
    "upserted_count",
    "qdrant_batch_count",
    "reused_count",
)
_FIRST = ("model_name", "index_version", "provider_type", "vector_dimension")


async def summarize_parts(ctx: StageContext) -> dict[str, Any]:
    summary: dict[str, Any] = {key: 0 for key in _SUMMED}
    summary.update({key: None for key in _FIRST})
    cost = Decimal("0")
    parts = 0
    async for part in ctx.store.iter_artifacts(StageName.embed):
        parts += 1
        for key in _SUMMED:
            summary[key] += int(part.get(key) or 0)
        for key in _FIRST:
            if summary[key] is None:
                summary[key] = part.get(key)
        cost += Decimal(str(part.get("cost") or "0"))
    summary["cost"] = str(cost)
    summary["parts"] = parts
    if summary["model_name"] is None:
        summary["model_name"] = settings.openai_embedding_model
    return summary


def embedding_result(summary: dict[str, Any]) -> EmbeddingResult:
    """Aggregated result for callers; vectors are never kept after the upserts."""
    dimension = summary.get("vector_dimension")
    return EmbeddingResult(
        vectors_by_chunk_id={},
        model_name=str(summary.get("model_name") or settings.openai_embedding_model),
        index_version=str(summary.get("index_version") or settings.document_index_version),
        provider_type=str(summary.get("provider_type") or ""),
        is_local=False,
        vector_dimension=int(dimension) if dimension is not None else settings.qdrant_vector_size,
        batch_count=int(summary.get("batch_count", 0)),
        retry_count=int(summary.get("retry_count", 0)),
        input_tokens=int(summary.get("input_tokens", 0)),
        total_tokens=int(summary.get("total_tokens", 0)),
        latency_ms=int(summary.get("latency_ms", 0)),
        approximate_cost_usd=Decimal(str(summary.get("cost") or "0")),
    )


async def log_embed_completed(ctx: StageContext, summary: dict[str, Any]) -> None:
    """``embed`` completed, then ``index`` started and completed, as the single pass emitted."""
    ctx.log_stage(
        "embed",
        "completed",
        embedding_batch_count=summary["batch_count"],
        embedding_retry_count=summary["retry_count"],
    )
    await ctx.recorder.emit_stage(
        stage="embed",
        stage_status="completed",
        outputs={
            "batch_count": summary["batch_count"],
            "retry_count": summary["retry_count"],
            "input_tokens": summary["input_tokens"],
            "total_tokens": summary["total_tokens"],
            "latency_ms": summary["latency_ms"],
        },
    )
    ctx.current_stage = "index"
    collection = ctx.options.vector_collection or settings.qdrant_collection
    ctx.log_stage("index", "started")
    await ctx.recorder.emit_stage(
        stage="index", stage_status="started", config={"collection": collection}
    )
    ctx.log_stage(
        "index",
        "completed",
        qdrant_upserted_count=summary["upserted_count"],
        qdrant_batch_count=summary["qdrant_batch_count"],
    )
    await ctx.recorder.emit_stage(
        stage="index",
        stage_status="completed",
        outputs={
            "qdrant_upserted_count": summary["upserted_count"],
            "qdrant_batch_count": summary["qdrant_batch_count"],
        },
    )
