from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings


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


@dataclass(frozen=True)
class QdrantUpsertResult:
    point_ids_by_chunk_id: dict[UUID, str]
    upserted_count: int
    batch_count: int


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
        point_id = f"{document_id}:{normalized_index_version}:{chunk_index}"
        if len(point_id) > 128:
            raise ValueError("qdrant point id exceeds max length")
        return point_id

    @staticmethod
    def _client() -> QdrantClient:
        if qdrant_module.qdrant_client is None:
            qdrant_module.init_qdrant()
        client = qdrant_module.qdrant_client
        if client is None:
            raise RuntimeError("Qdrant client is not initialized")
        return client

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

            point_id = chunk.qdrant_point_id or self.build_point_id(
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
