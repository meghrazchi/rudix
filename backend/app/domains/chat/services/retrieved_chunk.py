"""Retrieved chunk value object and converters from retrieval candidates (R05-01)."""

from dataclasses import dataclass
from uuid import UUID

from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievedChunk,
)
from app.domains.chat.services.hybrid_retrieval_service import (
    HybridCandidate,
)
from app.domains.chat.services.query_retrieval_service import (
    RetrievedCandidate,
)


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    original_rank: int | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None
    final_rank: int | None = None
    retrieval_source: str = "vector"
    graph_score: float | None = None
    graph_hops: int = 0
    keyword_score: float | None = None
    hybrid_score: float | None = None
    chunk_type: str = "text"
    # Parent-child context (F300): present when a child chunk was retrieved.
    chunk_level: int = 0
    parent_text: str | None = None


def _to_retrieved_chunk(candidate: RetrievedCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
        chunk_type=candidate.chunk_type,
        chunk_level=candidate.chunk_level,
        parent_text=candidate.parent_text,
    )


def _hybrid_to_retrieved_chunk(candidate: HybridCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
        retrieval_source=candidate.retrieval_source,
        keyword_score=candidate.keyword_score,
        hybrid_score=candidate.hybrid_score,
        chunk_type=getattr(candidate, "chunk_type", "text"),
        chunk_level=candidate.chunk_level,
        parent_text=candidate.parent_text,
    )


def _to_graph_retrieved_chunk(candidate: GraphRetrievedChunk) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
        retrieval_source="graph",
        graph_score=candidate.graph_score,
        graph_hops=candidate.graph_hops,
    )


def _merge_retrieved_chunks(
    vector_chunks: list[RetrievedChunk],
    graph_chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    insertion_order: list[str] = []

    def _merge_graph_hops(existing_hops: int, new_hops: int) -> int:
        if existing_hops == 0:
            return new_hops
        if new_hops == 0:
            return existing_hops
        return min(existing_hops, new_hops)

    def _upsert(chunk: RetrievedChunk) -> None:
        key = str(chunk.chunk_id)
        existing = merged.get(key)
        if existing is None:
            merged[key] = chunk
            insertion_order.append(key)
            return

        merged[key] = RetrievedChunk(
            document_id=existing.document_id,
            chunk_id=existing.chunk_id,
            filename=existing.filename or chunk.filename,
            page_number=(
                existing.page_number if existing.page_number is not None else chunk.page_number
            ),
            text=existing.text if len(existing.text) >= len(chunk.text) else chunk.text,
            similarity_score=max(existing.similarity_score, chunk.similarity_score),
            rerank_score=existing.rerank_score,
            rerank_rank=existing.rerank_rank,
            retrieval_source="merged",
            graph_score=max(
                existing.graph_score or 0.0,
                chunk.graph_score or 0.0,
            )
            or None,
            graph_hops=_merge_graph_hops(existing.graph_hops, chunk.graph_hops),
            chunk_type=existing.chunk_type,
            chunk_level=existing.chunk_level,
            parent_text=existing.parent_text or chunk.parent_text,
        )

    for chunk in vector_chunks:
        _upsert(chunk)
    for chunk in graph_chunks:
        _upsert(chunk)

    return [merged[key] for key in insertion_order]


def _with_original_ranks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    ranked_chunks: list[RetrievedChunk] = []
    for index, chunk in enumerate(chunks, start=1):
        ranked_chunks.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=index,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
                retrieval_source=chunk.retrieval_source,
                graph_score=chunk.graph_score,
                graph_hops=chunk.graph_hops,
                keyword_score=chunk.keyword_score,
                hybrid_score=chunk.hybrid_score,
                chunk_type=chunk.chunk_type,
                chunk_level=chunk.chunk_level,
                parent_text=chunk.parent_text,
            )
        )
    return ranked_chunks
