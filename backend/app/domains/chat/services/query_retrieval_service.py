from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.ai.providers.protocols import EmbeddingProvider, EmbeddingRequest
from app.domains.documents.services.qdrant_filters import build_organization_filter


class QdrantClientLike(Protocol):
    def search(self, **kwargs: object) -> list[Any]: ...

    def query_points(self, **kwargs: object) -> Any: ...


@dataclass(frozen=True)
class RetrievedCandidate:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    section_path: str | None = None
    chunk_level: int = 0
    parent_chunk_id: UUID | None = None
    parent_text: str | None = None
    chunk_type: str = "text"


@dataclass(frozen=True)
class QueryRetrievalResult:
    embedding_model: str
    embedding_prompt_tokens: int
    query_vector: list[float]
    candidates: list[RetrievedCandidate]


def _is_async_client(client: Any) -> bool:
    return inspect.iscoroutinefunction(getattr(client, "query_points", None))


class QueryRetrievalService:
    def __init__(
        self,
        *,
        embedding_model: str | None = None,
        qdrant_collection: str | None = None,
        vector_size: int | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        qdrant_client: QdrantClientLike | None = None,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> None:
        self.embedding_model = (embedding_model or settings.openai_embedding_model).strip()
        self.qdrant_collection = (qdrant_collection or settings.qdrant_collection).strip()
        self.vector_size = vector_size or settings.qdrant_vector_size
        self._embedding_provider = embedding_provider
        self._qdrant_client = qdrant_client
        self._session_factory = session_factory

    def _resolve_embedding_provider(self) -> EmbeddingProvider:
        if self._embedding_provider is None:
            from app.domains.ai.providers.factory import default_provider_factory

            self._embedding_provider = default_provider_factory.get_embedding_provider()
        return self._embedding_provider

    def _resolve_qdrant_client(self) -> QdrantClientLike:
        if self._qdrant_client is None:
            if qdrant_module.qdrant_client is None:
                qdrant_module.init_qdrant()
            if qdrant_module.qdrant_client is None:
                raise RuntimeError("Qdrant client is not initialized")
            self._qdrant_client = qdrant_module.qdrant_client
        return self._qdrant_client

    def _resolve_async_path_client(self) -> Any:
        """Injected client (constructor or module override), else the async search client."""
        if self._qdrant_client is not None:
            return self._qdrant_client
        injected = qdrant_module.injected_sync_client()
        if injected is not None:
            return injected
        return qdrant_module.get_async_search_client()

    async def embed_query(
        self,
        *,
        question: str,
        provider: EmbeddingProvider | None = None,
    ) -> tuple[list[float], int]:
        if not question.strip():
            raise ValueError("question is required")

        embedding_provider = provider or self._resolve_embedding_provider()
        response = await embedding_provider.embed(
            EmbeddingRequest(texts=[question], model=self.embedding_model)
        )
        if not response.vectors:
            raise RuntimeError("Embedding response did not include vectors")

        vector = response.vectors[0]
        if len(vector) != self.vector_size:
            raise RuntimeError(
                f"Embedding dimension mismatch: expected {self.vector_size}, got {len(vector)}"
            )
        return vector, response.prompt_tokens

    @staticmethod
    def _query_filter(
        *,
        organization_id: UUID,
        document_ids: list[UUID] | None,
        index_version: str | None,
        index_versions: Sequence[str] | None,
    ) -> object:
        return build_organization_filter(
            organization_id=str(organization_id),
            document_ids=[str(document_id) for document_id in document_ids]
            if document_ids is not None
            else None,
            index_version=index_version,
            index_versions=index_versions,
        )

    def retrieve_candidates(
        self,
        *,
        query_vector: list[float],
        organization_id: UUID,
        document_ids: list[UUID] | None,
        initial_top_k: int,
        index_version: str | None = None,
        qdrant_client: QdrantClientLike | None = None,
        index_versions: Sequence[str] | None = None,
    ) -> list[RetrievedCandidate]:
        """Synchronous search (scripts, evaluation, safety scoring); payload parent text."""
        if initial_top_k < 1:
            raise ValueError("initial_top_k must be at least 1")
        if document_ids is not None and len(document_ids) == 0:
            return []

        query_filter = self._query_filter(
            organization_id=organization_id,
            document_ids=document_ids,
            index_version=index_version,
            index_versions=index_versions,
        )
        client = qdrant_client or self._resolve_qdrant_client()
        results = self._search_results(
            qdrant_client=client,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=initial_top_k,
        )
        return self._to_candidates(results, organization_id, document_ids)

    async def aretrieve_candidates(
        self,
        *,
        query_vector: list[float],
        organization_id: UUID,
        document_ids: list[UUID] | None,
        initial_top_k: int,
        index_version: str | None = None,
        qdrant_client: QdrantClientLike | None = None,
        index_versions: Sequence[str] | None = None,
    ) -> list[RetrievedCandidate]:
        """Request-path search through ``AsyncQdrantClient`` (R06-07).

        A sync client (an injected ``QdrantClientLike``) runs in a thread, as all searches
        did before. With ``QDRANT_STORE_PARENT_TEXT=false`` parent text missing from the
        payload is read from ``document_chunks`` (``resolve_parent_texts``).
        """
        if initial_top_k < 1:
            raise ValueError("initial_top_k must be at least 1")
        if document_ids is not None and len(document_ids) == 0:
            return []

        client = qdrant_client or self._resolve_async_path_client()
        if not _is_async_client(client):
            candidates = await asyncio.to_thread(
                self.retrieve_candidates,
                query_vector=query_vector,
                organization_id=organization_id,
                document_ids=document_ids,
                initial_top_k=initial_top_k,
                index_version=index_version,
                qdrant_client=client,
                index_versions=index_versions,
            )
        else:
            candidates = await self._search_async(
                client,
                query_vector=query_vector,
                organization_id=organization_id,
                document_ids=document_ids,
                initial_top_k=initial_top_k,
                index_version=index_version,
                index_versions=index_versions,
            )
        if settings.qdrant_store_parent_text:
            return candidates
        return await self.resolve_parent_texts(candidates, organization_id=organization_id)

    async def _search_async(
        self,
        client: Any,
        *,
        query_vector: list[float],
        organization_id: UUID,
        document_ids: list[UUID] | None,
        initial_top_k: int,
        index_version: str | None,
        index_versions: Sequence[str] | None,
    ) -> list[RetrievedCandidate]:
        query_filter = self._query_filter(
            organization_id=organization_id,
            document_ids=document_ids,
            index_version=index_version,
            index_versions=index_versions,
        )
        response = await client.query_points(
            collection_name=self.qdrant_collection,
            query=query_vector,
            query_filter=query_filter,
            limit=initial_top_k,
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(response, "points", None)
        if points is None:
            raise RuntimeError("Qdrant query_points returned no points")
        return self._to_candidates(list(points), organization_id, document_ids)

    async def resolve_parent_texts(
        self, candidates: list[RetrievedCandidate], *, organization_id: UUID
    ) -> list[RetrievedCandidate]:
        """Fill ``parent_text`` of child candidates from ``document_chunks`` (R06-07).

        One batched query in a short session, bound to the organisation and joined to
        ``documents.organization_id``, so a parent of another organisation is never read.
        """
        wanted = {
            c.parent_chunk_id
            for c in candidates
            if c.chunk_level == 1 and c.parent_chunk_id is not None and not c.parent_text
        }
        if not wanted:
            return candidates

        from app.db.tenant_context import tenant_context_scope
        from app.models.document import Document, DocumentChunk

        factory = self._session_factory
        if factory is None:
            from app.db.session import SessionLocal

            factory = SessionLocal
        statement = (
            select(DocumentChunk.id, DocumentChunk.text)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_(list(wanted)), Document.organization_id == organization_id)
        )
        with tenant_context_scope(organization_id):
            async with factory() as session:
                rows = (await session.execute(statement)).all()
        texts = {row[0]: str(row[1]).strip() for row in rows if row[1]}
        return [
            replace(c, parent_text=texts[c.parent_chunk_id])
            if c.parent_chunk_id in texts and not c.parent_text
            else c
            for c in candidates
        ]

    def _to_candidates(
        self,
        results: list[Any],
        organization_id: UUID,
        document_ids: list[UUID] | None,
    ) -> list[RetrievedCandidate]:
        normalized_organization_id = str(organization_id)
        normalized_document_ids = (
            {str(document_id) for document_id in document_ids}
            if document_ids is not None
            else set()
        )
        candidates: list[RetrievedCandidate] = []
        for result in results:
            payload = getattr(result, "payload", None) or {}
            payload_org = str(payload.get("organization_id", "")).strip()
            if payload_org != normalized_organization_id:
                continue

            try:
                document_id = UUID(str(payload["document_id"]))
                chunk_id = UUID(str(payload["chunk_id"]))
            except (KeyError, TypeError, ValueError):
                continue

            if normalized_document_ids and str(document_id) not in normalized_document_ids:
                continue

            filename = str(payload.get("filename", "")).strip()
            text = str(payload.get("text", "")).strip()
            if not filename or not text:
                continue

            raw_page_number = payload.get("page_number")
            page_number = (
                raw_page_number
                if isinstance(raw_page_number, int) and raw_page_number >= 1
                else None
            )
            similarity_score = float(getattr(result, "score", 0.0) or 0.0)
            section_path = str(payload.get("section_path") or "").strip() or None
            chunk_level = int(payload.get("chunk_level") or 0)
            parent_chunk_id: UUID | None = None
            raw_parent_id = payload.get("parent_chunk_id")
            if raw_parent_id:
                try:
                    parent_chunk_id = UUID(str(raw_parent_id))
                except (TypeError, ValueError):
                    parent_chunk_id = None
            parent_text = str(payload.get("parent_text") or "").strip() or None
            chunk_type = str(payload.get("chunk_type") or "text").strip() or "text"
            if chunk_type not in ("text", "table", "image"):
                chunk_type = "text"

            candidates.append(
                RetrievedCandidate(
                    document_id=document_id,
                    chunk_id=chunk_id,
                    filename=filename,
                    page_number=page_number,
                    text=text,
                    similarity_score=similarity_score,
                    section_path=section_path,
                    chunk_level=chunk_level,
                    parent_chunk_id=parent_chunk_id,
                    parent_text=parent_text,
                    chunk_type=chunk_type,
                )
            )

        return candidates

    async def embed_and_retrieve(
        self,
        *,
        question: str,
        organization_id: UUID,
        document_ids: list[UUID] | None,
        initial_top_k: int,
        index_version: str | None = None,
        provider: EmbeddingProvider | None = None,
        qdrant_client: QdrantClientLike | None = None,
        index_versions: Sequence[str] | None = None,
    ) -> QueryRetrievalResult:
        query_vector, prompt_tokens = await self.embed_query(
            question=question,
            provider=provider,
        )
        candidates = await self.aretrieve_candidates(
            query_vector=query_vector,
            organization_id=organization_id,
            document_ids=document_ids,
            initial_top_k=initial_top_k,
            index_version=index_version,
            qdrant_client=qdrant_client,
            index_versions=index_versions,
        )
        return QueryRetrievalResult(
            embedding_model=self.embedding_model,
            embedding_prompt_tokens=prompt_tokens,
            query_vector=query_vector,
            candidates=candidates,
        )

    def _search_results(
        self,
        *,
        qdrant_client: QdrantClientLike,
        query_vector: list[float],
        query_filter: object,
        limit: int,
    ) -> list[Any]:
        search_method = getattr(qdrant_client, "search", None)
        if callable(search_method):
            return list(
                search_method(
                    collection_name=self.qdrant_collection,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
            )

        query_points_method = getattr(qdrant_client, "query_points", None)
        if callable(query_points_method):
            response = query_points_method(
                collection_name=self.qdrant_collection,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            points = getattr(response, "points", None)
            if points is None:
                raise RuntimeError("Qdrant query_points returned no points")
            return list(points)

        raise AttributeError("Qdrant client has neither 'search' nor 'query_points'")
