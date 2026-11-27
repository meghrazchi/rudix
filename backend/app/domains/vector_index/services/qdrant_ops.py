"""Qdrant collection and alias operations of the generation lifecycle (R06-08).

Operator paths only (CLI, startup reconcile, verify, swap, drop): they use the
synchronous client of ``app.clients.qdrant_client`` in a worker thread, never the request
path. Calls match ``qdrant-client`` 1.20.0: ``update_collection_aliases(
change_aliases_operations=[...])`` with ``CreateAliasOperation(create_alias=CreateAlias(
collection_name, alias_name))`` and ``DeleteAliasOperation(delete_alias=DeleteAlias(
alias_name))``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from qdrant_client.http.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    FieldCondition,
    Filter,
    MatchAny,
    VectorParams,
)

from app.clients import qdrant_client as qdrant_module
from app.clients.factory import qdrant_distance_to_model
from app.clients.qdrant_tuning import create_collection_kwargs, vectors_on_disk
from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings.enums import QdrantDistance

logger = get_logger("vector_index")


def _client() -> Any:
    if qdrant_module.qdrant_client is None:
        qdrant_module.init_qdrant()
    if qdrant_module.qdrant_client is None:
        raise RuntimeError("Qdrant client is not initialized")
    return qdrant_module.qdrant_client


def _vector_params_sync(collection_name: str) -> tuple[int, str] | None:
    client = _client()
    if not client.collection_exists(collection_name):
        return None
    vectors = getattr(client.get_collection(collection_name).config.params, "vectors", None)
    distance = str(getattr(vectors, "distance", "") or "").lower().split(".")[-1]
    return int(getattr(vectors, "size", 0) or 0), distance


async def vector_params(collection_name: str) -> tuple[int, str] | None:
    """(vector size, distance) of an existing collection, or None when it is missing."""
    return await asyncio.to_thread(_vector_params_sync, collection_name)


async def alias_target(alias: str) -> str | None:
    _client()
    return await asyncio.to_thread(qdrant_module.alias_target, alias)


def _create_collection_sync(collection_name: str, vector_size: int, distance: str) -> None:
    client = _client()
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=qdrant_distance_to_model(QdrantDistance(distance)),
                **vectors_on_disk(settings),
            ),
            **create_collection_kwargs(settings),
        )
        logger.info(
            "vector_index.collection.created",
            collection=collection_name,
            vector_size=vector_size,
            distance=distance,
        )
    qdrant_module.ensure_qdrant_payload_indexes(collection_name)


async def create_collection(collection_name: str, *, vector_size: int, distance: str) -> None:
    """Create the generation's collection and payload indexes (idempotent)."""
    await asyncio.to_thread(_create_collection_sync, collection_name, vector_size, distance)


async def create_alias(alias: str, collection_name: str) -> None:
    """Point a new alias at the collection (adoption): one call, one operation."""
    operation = CreateAliasOperation(
        create_alias=CreateAlias(collection_name=collection_name, alias_name=alias)
    )
    await asyncio.to_thread(
        _client().update_collection_aliases, change_aliases_operations=[operation]
    )


async def swap_alias(alias: str, collection_name: str) -> None:
    """Move the alias in ONE ``update_collection_aliases`` call (delete then create).

    Qdrant applies the operations of one call atomically, so no search sees the alias
    missing or pointing at a half state.
    """
    operations: list[Any] = [
        DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias)),
        CreateAliasOperation(
            create_alias=CreateAlias(collection_name=collection_name, alias_name=alias)
        ),
    ]
    await asyncio.to_thread(
        _client().update_collection_aliases, change_aliases_operations=operations
    )


async def delete_collection(collection_name: str) -> None:
    await asyncio.to_thread(_client().delete_collection, collection_name=collection_name)


def _count_sync(collection_name: str, index_versions: Sequence[str]) -> int:
    count_filter = Filter(
        must=[FieldCondition(key="index_version", match=MatchAny(any=list(index_versions)))]
    )
    result = _client().count(collection_name=collection_name, count_filter=count_filter, exact=True)
    return int(getattr(result, "count", 0))


async def count_points(collection_name: str, *, index_versions: Sequence[str]) -> int:
    """Exact point count of the active index versions in the collection."""
    return await asyncio.to_thread(_count_sync, collection_name, list(index_versions))
