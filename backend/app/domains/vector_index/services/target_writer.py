"""Write chunk rows into one generation's collection with its own model (R06-08).

Shared by the reindex build and the ingestion dual write. Vectors come, in this order,
from the caller (the same model already embedded them), from the target collection
(A1 reuse: same organisation, model and chunk hash), or from the embedding provider with
the target's model. Points carry the target's model in ``embedding_model``.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.domains.documents.services.embedding_service import EmbeddingService
from app.domains.vector_index.services.generation_service import GenerationTarget

logger = get_logger("vector_index")

# base service -> model -> service; weak keys so a replaced base drops its derived services.
_services: weakref.WeakKeyDictionary[Any, dict[str, Any]] = weakref.WeakKeyDictionary()


def embedding_service_for(model: str, base: Any) -> Any:
    """``base`` when it already embeds with ``model``, else a cached service for ``model``.

    The new service shares the base's provider (the request names the model), so tests and
    local providers keep their injected provider.
    """
    base_model = str(getattr(base, "model_name", "") or "").strip()
    if not base_model or base_model == model:
        return base
    by_model = _services.setdefault(base, {})
    service = by_model.get(model)
    if service is None:
        service = EmbeddingService(
            model_name=model,
            provider=getattr(base, "_provider", None),
            provider_type=getattr(base, "provider_type", None),
        )
        by_model[model] = service
    return service


@dataclass
class TargetWrite:
    vectors: dict[UUID, list[float]]
    upserted: int
    reused: int
    embedded: int
    input_tokens: int = 0
    total_tokens: int = 0
    cost: Decimal = Decimal("0")
    result: Any = None
    upsert: Any = None


class TargetDimensionError(ValueError):
    pass


async def _lookup(
    qdrant_service: Any, target: GenerationTarget, organization_id: UUID, rows: list[Any]
) -> dict[str, list[float]]:
    hashes = [row.chunk_hash for row in rows if row.chunk_hash]
    if not hashes:
        return {}
    try:
        return dict(
            await qdrant_service.find_reusable_vectors(
                organization_id=organization_id,
                embedding_model=target.embedding_model,
                chunk_hashes=hashes,
                collection_name=target.collection_name,
                vector_size=target.vector_size,
            )
        )
    except Exception as exc:
        logger.warning(
            "vector_index.reuse_lookup_failed",
            organization_id=str(organization_id),
            collection=target.collection_name,
            error_type=type(exc).__name__,
        )
        return {}


async def embed_for_target(
    *,
    qdrant_service: Any,
    embedding_service: Any,
    target: GenerationTarget,
    organization_id: UUID,
    rows: list[Any],
    known_vectors: dict[UUID, list[float]] | None = None,
) -> TargetWrite:
    """Vectors of ``rows`` for the target, reusing before calling the provider."""
    vectors = {
        chunk_id: vector
        for chunk_id, vector in (known_vectors or {}).items()
        if len(vector) == target.vector_size
    }
    pending = [row for row in rows if row.id not in vectors]
    found = await _lookup(qdrant_service, target, organization_id, pending) if pending else {}
    reused = 0
    for row in pending:
        vector = found.get(row.chunk_hash) if row.chunk_hash else None
        if vector is not None and len(vector) == target.vector_size:
            vectors[row.id] = vector
            reused += 1
    misses = [row for row in rows if row.id not in vectors]
    write = TargetWrite(vectors=vectors, upserted=0, reused=reused, embedded=len(misses))
    if misses:
        service = embedding_service_for(target.embedding_model, embedding_service)
        result = await service.embed_chunks(chunks=misses)
        for chunk_id, vector in result.vectors_by_chunk_id.items():
            if len(vector) != target.vector_size:
                raise TargetDimensionError(
                    f"embedding dimension mismatch: expected {target.vector_size}, "
                    f"got {len(vector)}"
                )
            vectors[chunk_id] = vector
        write.result = result
        write.input_tokens = int(getattr(result, "input_tokens", 0) or 0)
        write.total_tokens = int(getattr(result, "total_tokens", 0) or 0)
        write.cost = Decimal(str(getattr(result, "approximate_cost_usd", 0) or 0))
    missing = [row.id for row in rows if row.id not in vectors]
    if missing:
        raise TargetDimensionError("embedding generation did not cover all chunks")
    return write


async def write_rows(
    *,
    qdrant_service: Any,
    embedding_service: Any,
    target: GenerationTarget,
    document: Any,
    rows: list[Any],
    parent_text: dict[UUID, str] | None,
    ingest_run_id: str,
    known_vectors: dict[UUID, list[float]] | None = None,
) -> TargetWrite:
    """Embed (or reuse) and upsert ``rows`` into the target collection."""
    write = await embed_for_target(
        qdrant_service=qdrant_service,
        embedding_service=embedding_service,
        target=target,
        organization_id=document.organization_id,
        rows=rows,
        known_vectors=known_vectors,
    )
    if not rows:
        return write
    write.upsert = await qdrant_service.upsert_chunks(
        organization_id=document.organization_id,
        user_id=document.uploaded_by_user_id,
        document_id=document.id,
        filename=document.filename,
        file_type=document.file_type,
        chunks=rows,
        vectors_by_chunk_id=write.vectors,
        chunking_strategy=getattr(document, "chunking_strategy", None),
        chunking_profile_version=getattr(document, "chunking_profile_version", None),
        parent_text_by_chunk_id=parent_text or None,
        collection_name=target.collection_name,
        ingest_run_id=ingest_run_id,
        embedding_model=target.embedding_model,
        vector_size=target.vector_size,
    )
    write.upserted = int(getattr(write.upsert, "upserted_count", len(rows)))
    return write
