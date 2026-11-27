from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.http.models import FieldCondition, MatchAny, MatchValue, PointStruct

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.core.logging import get_logger
from app.domains.documents.services.qdrant_filters import build_organization_filter

logger = get_logger("documents.qdrant")


class ChunkLike(Protocol):
    id: UUID
    document_id: UUID
    page_number: int | None
    chunk_index: int
    text: str
    token_count: int
    qdrant_point_id: str | None
    embedding_model: str
    index_version: str
    chunk_hash: str | None
    section_path: str | None
    language: str | None
    # Hierarchical fields (F211); None for flat chunks.
    chunk_level: int | None
    parent_chunk_id: UUID | None
    child_count: int | None
    # Table-aware chunking (F298).
    chunk_type: str
    table_metadata: dict | None


@dataclass(frozen=True)
class QdrantUpsertResult:
    point_ids_by_chunk_id: dict[UUID, str]
    upserted_count: int
    batch_count: int


@dataclass(frozen=True)
class QdrantDeleteResult:
    deleted: bool


def resolve_write_targets() -> list[str]:
    """Collections a document write goes to (R06-01 seam; A2 adds a building generation)."""
    return [settings.qdrant_collection]


async def _call(method: Callable[..., Any], **kwargs: Any) -> Any:
    """Await an ``AsyncQdrantClient`` call; an injected sync client returns directly."""
    result = method(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


class QdrantService:
    """Vector index interactions.

    ``collection_name`` on writes defaults to ``None``, which means the configured
    ``QDRANT_COLLECTION`` (the behaviour before the argument existed).

    R06-07: writes go through ``AsyncQdrantClient`` with ``QDRANT_WRITE_TIMEOUT_SECONDS``
    (an injected sync client, ``qdrant_client.injected_sync_client()``, is used as is).
    The collection is ensured at startup and in the migrate job, not here: an upsert is
    one round trip per batch and a delete one call. A write that finds the configured
    collection missing (404) bootstraps it once and retries.
    """

    def __init__(self, *, batch_size: int = 128) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.batch_size = batch_size

    @staticmethod
    def build_point_id(
        *,
        document_id: UUID,
        chunk_index: int,
        index_version: str,
    ) -> str:
        normalized_index_version = index_version.strip()
        if not normalized_index_version:
            raise ValueError("index_version is required")
        legacy_key = f"{document_id}:{normalized_index_version}:{chunk_index}"
        # Qdrant point IDs must be unsigned integers or UUID values.
        return str(uuid5(NAMESPACE_URL, legacy_key))

    @staticmethod
    def _client() -> Any:
        injected = qdrant_module.injected_sync_client()
        if injected is not None:
            return injected
        return qdrant_module.get_async_write_client()

    async def _request(self, operation: str, **kwargs: Any) -> Any:
        method = getattr(self._client(), operation)
        try:
            return await _call(method, **kwargs)
        except UnexpectedResponse as exc:
            if exc.status_code != 404 or kwargs["collection_name"] != settings.qdrant_collection:
                raise
            logger.warning(
                "qdrant.collection.missing_on_write",
                collection=kwargs["collection_name"],
                operation=operation,
            )
            from app.clients.qdrant_bootstrap import bootstrap

            if not await asyncio.to_thread(bootstrap):
                raise
            return await _call(method, **kwargs)

    @staticmethod
    def _is_valid_qdrant_point_id(point_id: str) -> bool:
        normalized = point_id.strip()
        if not normalized:
            return False
        if normalized.isdigit():
            return True
        try:
            UUID(normalized)
            return True
        except ValueError:
            return False

    async def upsert_chunks(
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        document_id: UUID,
        filename: str,
        file_type: str,
        chunks: list[ChunkLike],
        vectors_by_chunk_id: dict[UUID, list[float]],
        chunking_strategy: str | None = None,
        chunking_profile_version: str | None = None,
        parent_text_by_chunk_id: dict[UUID, str] | None = None,
        collection_name: str | None = None,
        ingest_run_id: str | None = None,
    ) -> QdrantUpsertResult:
        if not chunks:
            return QdrantUpsertResult(point_ids_by_chunk_id={}, upserted_count=0, batch_count=0)

        point_ids_by_chunk_id: dict[UUID, str] = {}
        points: list[PointStruct] = []
        for chunk in chunks:
            vector = vectors_by_chunk_id.get(chunk.id)
            if vector is None:
                raise ValueError(f"missing embedding vector for chunk {chunk.id}")
            if len(vector) != settings.qdrant_vector_size:
                raise ValueError(
                    f"embedding dimension mismatch for chunk {chunk.id}: "
                    f"expected {settings.qdrant_vector_size}, got {len(vector)}"
                )

            point_id = chunk.qdrant_point_id
            if point_id is None or not self._is_valid_qdrant_point_id(point_id):
                point_id = self.build_point_id(
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    index_version=chunk.index_version,
                )
            point_ids_by_chunk_id[chunk.id] = point_id
            payload: dict[str, Any] = {
                "organization_id": str(organization_id),
                "user_id": str(user_id),
                "document_id": str(document_id),
                "chunk_id": str(chunk.id),
                "filename": filename,
                "file_type": file_type,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "token_count": chunk.token_count,
                "embedding_model": chunk.embedding_model,
                "index_version": chunk.index_version,
                "chunk_hash": chunk.chunk_hash,
                "section_path": chunk.section_path,
                "language": chunk.language,
                "chunking_strategy": chunking_strategy,
                "chunking_profile_version": chunking_profile_version,
                "chunk_level": chunk.chunk_level,
                "parent_chunk_id": (str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None),
                "child_count": chunk.child_count,
                "chunk_type": getattr(chunk, "chunk_type", "text"),
            }
            if settings.qdrant_store_parent_text:
                payload["parent_text"] = (parent_text_by_chunk_id or {}).get(chunk.id)
            if ingest_run_id is not None:
                # R06-06: the run that wrote the point; the index stage deletes the rest.
                payload["ingest_run_id"] = ingest_run_id
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        batch_count = 0
        for start in range(0, len(points), self.batch_size):
            await self._request(
                "upsert",
                collection_name=collection_name or settings.qdrant_collection,
                points=points[start : start + self.batch_size],
                wait=True,
            )
            batch_count += 1

        return QdrantUpsertResult(
            point_ids_by_chunk_id=point_ids_by_chunk_id,
            upserted_count=len(points),
            batch_count=batch_count,
        )

    async def delete_document_points(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        index_version: str | None = None,
        collection_name: str | None = None,
    ) -> QdrantDeleteResult:
        filter_selector = build_organization_filter(
            organization_id=str(organization_id),
            document_ids=[str(document_id)],
            index_version=index_version,
        )
        await self._request(
            "delete",
            collection_name=collection_name or settings.qdrant_collection,
            points_selector=filter_selector,
            wait=True,
        )
        return QdrantDeleteResult(deleted=True)

    async def find_reusable_vectors(
        self,
        *,
        organization_id: UUID,
        embedding_model: str,
        chunk_hashes: Iterable[str | None],
        collection_name: str | None = None,
    ) -> dict[str, list[float]]:
        """Stored vectors by chunk hash for this organisation and embedding model (R06-06).

        One scroll per call. The filter always carries ``organization_id``, so a vector is
        never reused across organisations; a hit whose dimension differs from
        ``QDRANT_VECTOR_SIZE`` is ignored (the chunk is embedded again).
        """
        hashes = sorted({value for value in chunk_hashes if value})
        if not hashes or not embedding_model.strip():
            return {}
        query_filter = build_organization_filter(organization_id=str(organization_id))
        query_filter.must = [
            *(query_filter.must or []),  # type: ignore[misc]
            FieldCondition(key="embedding_model", match=MatchValue(value=embedding_model)),
            FieldCondition(key="chunk_hash", match=MatchAny(any=hashes)),
        ]
        points, _ = await self._request(
            "scroll",
            collection_name=collection_name or settings.qdrant_collection,
            scroll_filter=query_filter,
            limit=len(hashes),
            with_payload=["chunk_hash", "organization_id"],
            with_vectors=True,
        )
        found: dict[str, list[float]] = {}
        for point in points:
            payload = getattr(point, "payload", None) or {}
            chunk_hash = payload.get("chunk_hash")
            vector = getattr(point, "vector", None)
            if (
                chunk_hash in hashes
                and payload.get("organization_id") == str(organization_id)
                and isinstance(vector, list)
                and len(vector) == settings.qdrant_vector_size
            ):
                found.setdefault(str(chunk_hash), [float(value) for value in vector])
        return found

    async def delete_stale_document_points(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        index_version: str,
        ingest_run_id: str,
        collection_name: str | None = None,
    ) -> None:
        """Delete the document's points of this index version not written by this run."""
        query_filter = build_organization_filter(
            organization_id=str(organization_id),
            document_ids=[str(document_id)],
            index_version=index_version,
        )
        query_filter.must_not = [
            FieldCondition(key="ingest_run_id", match=MatchValue(value=ingest_run_id))
        ]
        await self._request(
            "delete",
            collection_name=collection_name or settings.qdrant_collection,
            points_selector=query_filter,
            wait=True,
        )

    async def count_document_points(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        index_version: str,
        collection_name: str | None = None,
    ) -> int:
        result = await self._request(
            "count",
            collection_name=collection_name or settings.qdrant_collection,
            count_filter=build_organization_filter(
                organization_id=str(organization_id),
                document_ids=[str(document_id)],
                index_version=index_version,
            ),
            exact=True,
        )
        return int(getattr(result, "count", 0))
