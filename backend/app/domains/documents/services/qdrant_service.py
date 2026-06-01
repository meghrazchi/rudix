from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.documents.services.qdrant_filters import build_organization_filter


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


@dataclass(frozen=True)
class QdrantUpsertResult:
    point_ids_by_chunk_id: dict[UUID, str]
    upserted_count: int
    batch_count: int


@dataclass(frozen=True)
class QdrantDeleteResult:
    deleted: bool


class QdrantService:
    """Vector index interactions."""

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
    def _client() -> QdrantClient:
        if qdrant_module.qdrant_client is None:
            qdrant_module.init_qdrant()
        client = qdrant_module.qdrant_client
        if client is None:
            raise RuntimeError("Qdrant client is not initialized")
        return client

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
    ) -> QdrantUpsertResult:
        if not chunks:
            return QdrantUpsertResult(point_ids_by_chunk_id={}, upserted_count=0, batch_count=0)

        client = self._client()
        qdrant_module.ensure_qdrant_collection()

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
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
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
                    },
                )
            )

        batch_count = 0
        for start in range(0, len(points), self.batch_size):
            batch_points = points[start : start + self.batch_size]
            client.upsert(
                collection_name=settings.qdrant_collection,
                points=batch_points,
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
    ) -> QdrantDeleteResult:
        client = self._client()
        qdrant_module.ensure_qdrant_collection()
        filter_selector = build_organization_filter(
            organization_id=str(organization_id),
            document_ids=[str(document_id)],
            index_version=index_version,
        )
        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=filter_selector,
            wait=True,
        )
        return QdrantDeleteResult(deleted=True)
