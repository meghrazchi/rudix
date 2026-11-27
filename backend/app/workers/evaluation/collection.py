"""Dedicated Qdrant collection for evaluation re-ingest (R06-12).

``QDRANT_EVALUATION_COLLECTION`` unset keeps the pre-0.6.0 behaviour: chunking-comparison
vectors go to the production collection under ``eval-`` index versions. When it is set,
eval re-ingest, eval retrieval, eval cleanup and the purge script use that collection, and
document deletion also deletes the document's points from it. Points keep the production
payload (``organization_id``, ``document_id``, ``index_version``), so every delete and
search is scoped by organisation exactly as in production.

This module imports no worker module at import time: ``app.workers.ingestion.deletion``
imports it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("evaluation.collection")

# (collection, vector size, distance) ensured by this process.
_ensured: set[tuple[str, int, str]] = set()


class EvaluationCollectionMismatchError(RuntimeError):
    """The evaluation collection cannot hold vectors of the active generation."""


def evaluation_collection() -> str | None:
    """The configured evaluation collection, or None (legacy behaviour)."""
    name = (settings.qdrant_evaluation_collection or "").strip()
    return name or None


async def _active_vector_params() -> tuple[int, str]:
    """(vector size, distance) of the active generation's collection (A2 helpers)."""
    from app.domains.vector_index.services import generation_service, qdrant_ops

    active = (await generation_service.resolve_write_targets())[0]
    params = await qdrant_ops.vector_params(active.collection_name)
    if params is None:
        return active.vector_size, settings.qdrant_distance.value
    size, distance = params
    return size or active.vector_size, distance or settings.qdrant_distance.value


async def ensure_evaluation_collection(collection: str) -> tuple[int, str]:
    """Create the collection and its payload indexes like the active generation's.

    Idempotent and cached per process. Raises ``EvaluationCollectionMismatchError`` when
    an existing evaluation collection has other vector parameters, or when re-ingest
    vectors (``QDRANT_VECTOR_SIZE``) would not fit the active generation (a model change
    in progress); an operator drops the collection, it is recreated on the next run.
    """
    from app.domains.vector_index.services import qdrant_ops

    size, distance = await _active_vector_params()
    key = (collection, size, distance)
    if key in _ensured:
        return size, distance
    if size != settings.qdrant_vector_size:
        raise EvaluationCollectionMismatchError(
            "active vector generation size differs from QDRANT_VECTOR_SIZE"
        )
    existing = await qdrant_ops.vector_params(collection)
    if existing is not None and (existing[0] != size or (existing[1] or distance) != distance):
        raise EvaluationCollectionMismatchError(
            "evaluation collection vector parameters differ from the active generation"
        )
    await qdrant_ops.create_collection(collection, vector_size=size, distance=distance)
    _ensured.add(key)
    logger.info(
        "evaluation.collection.ensured",
        collection=collection,
        vector_size=size,
        distance=distance,
    )
    return size, distance


def reset_ensured_cache() -> None:
    """Forget ensured collections (tests, or after an operator dropped the collection)."""
    _ensured.clear()


async def delete_document_evaluation_points(
    qdrant_service: Any, *, organization_id: UUID, document_id: UUID
) -> bool:
    """Delete one document's points (every index version) from the evaluation collection.

    Returns False when no evaluation collection is configured or it does not exist yet.
    The filter is the production one: organisation and document.
    """
    collection = evaluation_collection()
    if collection is None:
        return False
    try:
        await qdrant_service.delete_document_points(
            organization_id=organization_id,
            document_id=document_id,
            collection_name=collection,
        )
    except UnexpectedResponse as exc:
        if exc.status_code != 404:
            raise
        logger.info("evaluation.collection.missing_on_delete", collection=collection)
        return False
    return True
