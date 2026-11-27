"""Vector index generations in the embed and index stages (R06-08).

Legacy mode, and evaluation runs with their own ``vector_collection``, never get here:
``resolve_targets`` returns None and the stages behave as before.

Alias mode: the embed stage resolves the write targets once per stage run and keeps them
in its metrics, so the index stage works on the same collections:

- the primary target is the active generation, embedded with its model (the configured
  service when the models match, otherwise a service for the active model);
- while a generation is building, every batch is also written to it with its model
  (dual write). A dual-write failure never fails the document: the index stage then
  finds the count short, records no generation row, and the build fills the document.
- the index stage deletes the document's stale points in the building collection, counts
  them, and records ``vector_index_generation_documents`` (plus a ``document.embedding``
  usage event for the dual-write tokens) when the count equals the chunk rows.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import delete

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.documents.services.embedding_service import (
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from app.domains.vector_index.repositories import generations as repo
from app.domains.vector_index.services import generation_service
from app.domains.vector_index.services.generation_service import GenerationTarget
from app.domains.vector_index.services.target_writer import TargetDimensionError, write_rows
from app.models.vector_index import VectorIndexGenerationDocument
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.documents import index_version
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
)
from app.workers.ingestion.stages.base import StageName
from app.workers.ingestion.stages.embed_reuse import ReusedOnlyResult, embedding_model_of

logger = get_logger("worker.ingestion")

METRICS_KEY = "vector_targets"
WRITES_KEY = "generation_writes"


async def resolve_targets(ctx: StageContext) -> list[GenerationTarget] | None:
    if ctx.options.vector_collection is not None or generation_service.configured_alias() is None:
        return None
    targets = await generation_service.resolve_write_targets()
    if all(target.is_legacy for target in targets):
        return None
    return targets


def to_metrics(targets: list[GenerationTarget] | None) -> list[dict[str, Any]] | None:
    if targets is None:
        return None
    return [
        {
            "collection_name": t.collection_name,
            "embedding_model": t.embedding_model,
            "vector_size": t.vector_size,
            "generation": t.generation,
            "generation_id": str(t.generation_id) if t.generation_id else None,
            "state": t.state,
        }
        for t in targets
    ]


def from_metrics(ctx: StageContext) -> list[GenerationTarget] | None:
    data = (ctx.metrics.get(StageName.embed) or {}).get(METRICS_KEY)
    if not data:
        return None
    return [
        GenerationTarget(
            collection_name=str(item["collection_name"]),
            embedding_model=str(item["embedding_model"]),
            vector_size=int(item["vector_size"]),
            generation=item.get("generation"),
            generation_id=UUID(item["generation_id"]) if item.get("generation_id") else None,
            state=str(item.get("state") or "active"),
        )
        for item in data
    ]


def primary_uses_configured_service(ctx: StageContext, target: GenerationTarget) -> bool:
    return (
        embedding_model_of(ctx) == target.embedding_model
        and target.vector_size == settings.qdrant_vector_size
    )


def _document_view(ctx: StageContext, document: Any) -> Any:
    chunk = ctx.metrics[StageName.chunk]
    return SimpleNamespace(
        organization_id=document.organization_id,
        uploaded_by_user_id=document.uploaded_by_user_id,
        id=document.id,
        filename=document.filename,
        file_type=document.file_type,
        chunking_strategy=chunk.get("strategy_name"),
        chunking_profile_version=chunk.get("strategy_version"),
    )


async def write_primary_other_model(
    ctx: StageContext, document: Any, rows: list[Any], parents: dict, target: GenerationTarget
) -> tuple[dict[UUID, list[float]], Any, Any, int]:
    """The active generation uses another model than the configured service."""
    try:
        write = await write_rows(
            qdrant_service=ctx.deps.qdrant_service,
            embedding_service=ctx.deps.embedding_service,
            target=target,
            document=_document_view(ctx, document),
            rows=rows,
            parent_text=parents,
            ingest_run_id=ctx.run_id,
        )
    except (PermanentEmbeddingError, TargetDimensionError) as exc:
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
    except Exception as exc:
        raise DocumentPipelineTransientError(
            stage="index",
            code="QDRANT_UPSERT_FAILED",
            category="infrastructure",
            message="qdrant upsert failed",
        ) from exc
    result = write.result or ReusedOnlyResult(
        model_name=target.embedding_model,
        index_version=rows[0].index_version if rows else None,
        provider_type=None,
        vector_dimension=target.vector_size,
    )
    return write.vectors, result, write.upsert, write.reused


async def dual_write(
    ctx: StageContext,
    document: Any,
    rows: list[Any],
    parents: dict,
    *,
    vectors: dict[UUID, list[float]],
    primary: GenerationTarget,
    extra: list[GenerationTarget],
) -> dict[str, dict[str, Any]]:
    """Write the batch to building generations; returns tokens per generation id."""
    spent: dict[str, dict[str, Any]] = {}
    for target in extra:
        same_model = (target.embedding_model, target.vector_size) == (
            primary.embedding_model,
            primary.vector_size,
        )
        try:
            write = await write_rows(
                qdrant_service=ctx.deps.qdrant_service,
                embedding_service=ctx.deps.embedding_service,
                target=target,
                document=_document_view(ctx, document),
                rows=rows,
                parent_text=parents,
                ingest_run_id=ctx.run_id,
                known_vectors=vectors if same_model else None,
            )
        except Exception as exc:
            logger.warning(
                "vector_index.dual_write_failed",
                document_id=ctx.document_id_str,
                organization_id=ctx.organization_id,
                generation=target.generation,
                error_type=type(exc).__name__,
            )
            continue
        spent[str(target.generation_id)] = {
            "input_tokens": write.input_tokens,
            "total_tokens": write.total_tokens,
            "cost": str(write.cost),
        }
    return spent


def sum_generation_writes(parts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for part in parts:
        for generation_id, spent in (part.get(WRITES_KEY) or {}).items():
            entry = totals.setdefault(
                generation_id, {"input_tokens": 0, "total_tokens": 0, "cost": "0"}
            )
            entry["input_tokens"] += int(spent.get("input_tokens") or 0)
            entry["total_tokens"] += int(spent.get("total_tokens") or 0)
            entry["cost"] = str(Decimal(entry["cost"]) + Decimal(str(spent.get("cost") or 0)))
    return totals


async def _forget_unwritten_generations(
    ctx: StageContext, document: Any, targets: list[GenerationTarget]
) -> None:
    written = [t.generation_id for t in targets if t.generation_id is not None]
    statement = delete(VectorIndexGenerationDocument).where(
        VectorIndexGenerationDocument.document_id == document.id
    )
    if written:
        statement = statement.where(VectorIndexGenerationDocument.generation_id.not_in(written))
    async with ctx.deps.SessionLocal() as session, session.begin():
        result = await session.execute(statement)
    forgotten = int(getattr(result, "rowcount", 0) or 0)
    if forgotten > 0:
        logger.info(
            "vector_index.generation_documents.forgotten",
            document_id=ctx.document_id_str,
            organization_id=ctx.organization_id,
            rows=forgotten,
        )


async def record_generation_documents(
    ctx: StageContext,
    document: Any,
    cleanup: Callable[[dict[str, Any]], Awaitable[int]],
) -> int:
    """Index stage: clean, count, and record the document in each building generation.

    First, rows of this document in every generation this run did not write (a failed
    generation, or a building one this process did not see yet) are deleted: their points
    predate this run's chunk rows, so a rerun of the build must write the document again
    instead of skipping it.
    """
    targets = from_metrics(ctx)
    if not targets:
        return 0
    await _forget_unwritten_generations(ctx, document, targets)
    if len(targets) < 2:
        return 0
    expected = int(ctx.metrics[StageName.chunk]["embeddable_count"])
    spent = (ctx.metrics.get(StageName.embed) or {}).get(WRITES_KEY) or {}
    recorded = 0
    for target in targets[1:]:
        assert target.generation_id is not None
        try:
            count = await cleanup({"collection_name": target.collection_name})
        except Exception as exc:
            logger.warning(
                "vector_index.dual_write_cleanup_failed",
                document_id=ctx.document_id_str,
                generation=target.generation,
                error_type=type(exc).__name__,
            )
            count = -1
        async with ctx.deps.SessionLocal() as session, session.begin():
            if count != expected:
                # The build writes this document again (no row means not done).
                await session.execute(
                    delete(VectorIndexGenerationDocument).where(
                        VectorIndexGenerationDocument.generation_id == target.generation_id,
                        VectorIndexGenerationDocument.document_id == document.id,
                    )
                )
                logger.warning(
                    "vector_index.dual_write_incomplete",
                    document_id=ctx.document_id_str,
                    generation=target.generation,
                    point_count=count,
                    expected=expected,
                )
                continue
            await repo.record_generation_document(
                session,
                generation_id=target.generation_id,
                organization_id=document.organization_id,
                document_id=document.id,
                point_count=count,
            )
            tokens = spent.get(str(target.generation_id)) or {}
            if int(tokens.get("total_tokens") or 0) > 0 and ctx.options.record_usage_event:
                await ctx.deps.usage_repository.create_usage_event(
                    session,
                    organization_id=document.organization_id,
                    user_id=document.uploaded_by_user_id,
                    event_type="document.embedding",
                    model_name=target.embedding_model,
                    input_tokens=int(tokens.get("input_tokens") or 0),
                    output_tokens=None,
                    cost_usd=Decimal(str(tokens.get("cost") or 0)),
                    metadata={
                        "reason": "vector_reindex_dual_write",
                        "generation": target.generation,
                        "document_id": str(document.id),
                        "index_version": index_version(ctx),
                        "total_tokens": int(tokens.get("total_tokens") or 0),
                    },
                )
            recorded += 1
    return recorded
