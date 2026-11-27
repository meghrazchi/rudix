"""Chunk stage metrics, completion logs and the chunking snapshot (R06-01).

The metrics hold counts and configuration only; finalize rebuilds the document's
``chunking_config_snapshot`` from them so a resumed run writes the same snapshot.
"""

from __future__ import annotations

from typing import Any

from app.workers.ingestion.context import StageContext


def _adaptive(svc: Any) -> dict[str, Any] | None:
    selection = getattr(svc, "last_adaptive_selection", None)
    if selection is None:
        return None
    adaptive: dict[str, Any] = {
        "strategy": selection.strategy,
        "reason_codes": selection.reason_codes,
        "signals": None,
    }
    if selection.signals is not None:
        signals = selection.signals
        adaptive["signals"] = {
            "file_type": signals.file_type,
            "page_count": signals.page_count,
            "ocr_applied": signals.ocr_applied,
            "heading_density": signals.heading_density,
            "total_token_count": signals.total_token_count,
            "language": getattr(signals, "language", None),
        }
    return adaptive


def chunk_metrics(
    ctx: StageContext,
    svc: Any,
    chunks: list[Any],
    sections: list[Any],
    strategy: str,
    index_version: str,
) -> dict[str, Any]:
    is_hierarchical = any(c.chunk_level == 1 for c in chunks)
    return {
        "index_version": index_version,
        "chunk_count": len(chunks),
        "strategy_name": chunks[0].strategy_name if chunks else strategy,
        "strategy_version": chunks[0].strategy_version if chunks else "1.0",
        "chunk_size_tokens": getattr(svc, "chunk_size_tokens", None),
        "chunk_overlap_tokens": getattr(svc, "chunk_overlap_tokens", None),
        "embedding_model": getattr(svc, "embedding_model", None),
        "svc_index_version": getattr(svc, "index_version", None),
        "total_chunk_tokens": sum(c.token_count for c in chunks),
        "is_hierarchical": is_hierarchical,
        "parent_count": sum(1 for c in chunks if c.chunk_level == 0) if is_hierarchical else 0,
        "child_count": sum(1 for c in chunks if c.chunk_level == 1) if is_hierarchical else 0,
        "empty_pages": sum(1 for s in sections if not s.text.strip()),
        "adaptive": _adaptive(svc),
    }


async def log_chunk_completed(
    ctx: StageContext,
    svc: Any,
    chunks: list[Any],
    sections: list[Any],
    metrics: dict[str, Any],
    duration_ms: int,
) -> None:
    tokens = [c.token_count for c in chunks]
    avg_tokens = round(sum(tokens) / len(tokens), 1)
    adaptive = metrics["adaptive"]
    adaptive_log: dict[str, Any] = {}
    reason_codes: list[str] | None = None
    language: str | None = None
    if adaptive is not None:
        adaptive_log = {
            "adaptive_selected_strategy": adaptive["strategy"],
            "adaptive_reason_codes": adaptive["reason_codes"],
        }
        reason_codes = adaptive["reason_codes"]
        if adaptive["signals"] is not None:
            language = adaptive["signals"]["language"]
    final_strategy = metrics["strategy_name"]
    summary: dict[str, Any] = {
        "chunk_count": len(chunks),
        "avg_tokens": avg_tokens,
        "max_tokens": max(tokens),
        "min_tokens": min(tokens),
        "empty_pages": metrics["empty_pages"],
        "duration_ms": duration_ms,
        "strategy": final_strategy,
        "profile_source": ctx.options.profile_source,
    }
    if reason_codes is not None:
        summary["reason_codes"] = reason_codes
    if language is not None:
        summary["language"] = language
    ctx.log_stage("chunk", "completed", chunk_count=len(chunks), **adaptive_log)
    ctx.deps.log_chunking_event(
        event="document.chunking.completed",
        document_id=ctx.document_id_str,
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        strategy=final_strategy,
        chunk_count=len(chunks),
        avg_tokens=avg_tokens,
        max_tokens=max(tokens),
        min_tokens=min(tokens),
        duration_ms=duration_ms,
        profile_source=ctx.options.profile_source,
        reason_codes=reason_codes,
        empty_pages=metrics["empty_pages"],
        language=language,
        index_version=getattr(svc, "index_version", None),
    )
    await ctx.recorder.emit_stage(
        stage="chunk",
        stage_status="completed",
        outputs={"chunk_count": len(chunks), **adaptive_log, "metrics": summary},
    )


def chunking_snapshot(ctx: StageContext, embedding: dict[str, Any]) -> dict[str, Any]:
    """``documents.chunking_config_snapshot`` exactly as the single-pass worker wrote it."""
    chunk = ctx.metrics["chunk"]
    extract = ctx.metrics["extract"]
    snapshot: dict[str, Any] = {
        "strategy": chunk["strategy_name"],
        "strategy_version": chunk["strategy_version"],
        "chunk_size_tokens": chunk["chunk_size_tokens"],
        "chunk_overlap_tokens": chunk["chunk_overlap_tokens"],
        "embedding_model": chunk["embedding_model"],
        "index_version": chunk["svc_index_version"],
        "profile_source": ctx.options.profile_source,
        "ocr_applied": bool(extract.get("ocr_applied")),
        "total_chunk_count": chunk["chunk_count"],
        "total_chunk_tokens": chunk["total_chunk_tokens"],
    }
    if chunk.get("table_chunk_count", 0) > 0:
        snapshot["table_chunk_count"] = chunk["table_chunk_count"]
    if extract.get("advanced_extraction"):
        snapshot["document_profile"] = extract["document_profile"]
        snapshot["total_table_blocks"] = extract["total_table_blocks"]
        snapshot["total_image_blocks"] = extract["total_image_blocks"]
    if chunk["is_hierarchical"]:
        snapshot["hierarchical_mode"] = True
        snapshot["parent_chunk_count"] = chunk["parent_count"]
        snapshot["child_chunk_count"] = chunk["child_count"]
    adaptive = chunk.get("adaptive")
    if adaptive is not None:
        snapshot["adaptive_selected_strategy"] = adaptive["strategy"]
        snapshot["adaptive_reason_codes"] = adaptive["reason_codes"]
        if adaptive["signals"] is not None:
            signals = {k: v for k, v in adaptive["signals"].items() if k != "language"}
            snapshot["adaptive_signals"] = signals
    snapshot["embedding_provider_type"] = embedding.get("provider_type")
    snapshot["embedding_vector_dimension"] = embedding.get("vector_dimension")
    return snapshot
