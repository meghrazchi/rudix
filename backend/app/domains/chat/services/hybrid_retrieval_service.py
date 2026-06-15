from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievedCandidate
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HybridCandidate:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    section_path: str | None
    similarity_score: float
    keyword_score: float
    hybrid_score: float
    # "vector", "keyword", or "hybrid"
    retrieval_source: str
    exact_match_hit: bool = False
    vector_rank: int | None = None
    keyword_rank: int | None = None
    # Parent-child context (F300): populated for child chunks.
    chunk_level: int = 0
    parent_chunk_id: UUID | None = None
    parent_text: str | None = None


@dataclass(frozen=True)
class HybridRetrievalResult:
    candidates: list[HybridCandidate]
    vector_hit_count: int
    keyword_hit_count: int
    exact_match_tokens: list[str]


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion helpers
# ---------------------------------------------------------------------------


def _rrf_score(rank: int, k: int) -> float:
    return 1.0 / (k + rank)


def merge_with_rrf(
    *,
    vector_candidates: list[RetrievedCandidate],
    keyword_candidates: list[KeywordRetrievedCandidate],
    vector_weight: float,
    rrf_k: int,
    exact_match_boost: float,
    exact_match_tokens: list[str],
) -> list[HybridCandidate]:
    """Merge vector and keyword results using Reciprocal Rank Fusion.

    RRF formula: score = vector_weight/( k+v_rank ) + (1-vector_weight)/(k+kw_rank)
    Chunks only present in one source receive a penalty rank of len(other)+1.
    """
    keyword_weight = 1.0 - vector_weight

    # Build rank maps keyed by chunk_id string.
    vector_rank_map: dict[str, int] = {
        str(c.chunk_id): idx + 1 for idx, c in enumerate(vector_candidates)
    }
    keyword_rank_map: dict[str, int] = {
        str(c.chunk_id): idx + 1 for idx, c in enumerate(keyword_candidates)
    }

    vector_penalty = len(vector_candidates) + 1
    keyword_penalty = len(keyword_candidates) + 1

    # Index data from each source.
    vector_data: dict[str, RetrievedCandidate] = {
        str(c.chunk_id): c for c in vector_candidates
    }
    keyword_data: dict[str, KeywordRetrievedCandidate] = {
        str(c.chunk_id): c for c in keyword_candidates
    }

    all_chunk_ids = set(vector_data) | set(keyword_data)

    results: list[HybridCandidate] = []
    for chunk_id_str in all_chunk_ids:
        v_rank = vector_rank_map.get(chunk_id_str, vector_penalty)
        kw_rank = keyword_rank_map.get(chunk_id_str, keyword_penalty)

        rrf = (
            vector_weight * _rrf_score(v_rank, rrf_k)
            + keyword_weight * _rrf_score(kw_rank, rrf_k)
        )

        # Pull metadata from whichever source has this chunk.
        # Vector source is preferred for parent fields since the text is stored in Qdrant.
        chunk_level: int = 0
        parent_chunk_id: UUID | None = None
        parent_text: str | None = None
        if chunk_id_str in vector_data:
            vc = vector_data[chunk_id_str]
            chunk_id = vc.chunk_id
            document_id = vc.document_id
            filename = vc.filename
            page_number = vc.page_number
            text = vc.text
            section_path = vc.section_path
            similarity_score = vc.similarity_score
            chunk_level = vc.chunk_level
            parent_chunk_id = vc.parent_chunk_id
            parent_text = vc.parent_text
        else:
            kc = keyword_data[chunk_id_str]
            chunk_id = kc.chunk_id
            document_id = kc.document_id
            filename = kc.filename
            page_number = kc.page_number
            text = kc.text
            section_path = kc.section_path
            similarity_score = 0.0
            chunk_level = kc.chunk_level
            parent_chunk_id = kc.parent_chunk_id
            parent_text = kc.parent_text

        kw_data = keyword_data.get(chunk_id_str)
        keyword_score = kw_data.keyword_score if kw_data else 0.0
        exact_match_hit = kw_data.exact_match_hit if kw_data else False
        # Prefer keyword parent_text when vector did not supply it.
        if parent_text is None and kw_data is not None:
            parent_text = kw_data.parent_text
            if chunk_level == 0:
                chunk_level = kw_data.chunk_level
            if parent_chunk_id is None:
                parent_chunk_id = kw_data.parent_chunk_id

        # Apply exact-match boost to the final hybrid score.
        if exact_match_hit and exact_match_tokens:
            rrf = rrf * exact_match_boost

        # Determine retrieval source label.
        in_vector = chunk_id_str in vector_rank_map
        in_keyword = chunk_id_str in keyword_rank_map
        if in_vector and in_keyword:
            source = "hybrid"
        elif in_vector:
            source = "vector"
        else:
            source = "keyword"

        results.append(
            HybridCandidate(
                document_id=document_id,
                chunk_id=chunk_id,
                filename=filename,
                page_number=page_number,
                text=text,
                section_path=section_path,
                similarity_score=similarity_score,
                keyword_score=keyword_score,
                hybrid_score=rrf,
                retrieval_source=source,
                exact_match_hit=exact_match_hit,
                vector_rank=v_rank if in_vector else None,
                keyword_rank=kw_rank if in_keyword else None,
                chunk_level=chunk_level,
                parent_chunk_id=parent_chunk_id,
                parent_text=parent_text,
            )
        )

    results.sort(key=lambda c: c.hybrid_score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class HybridRetrievalService:
    """Merges Qdrant vector results and PostgreSQL FTS results via RRF."""

    def merge(
        self,
        *,
        vector_candidates: list[RetrievedCandidate],
        keyword_candidates: list[KeywordRetrievedCandidate],
        exact_match_tokens: list[str],
        vector_weight: float,
        rrf_k: int,
        exact_match_boost: float,
    ) -> HybridRetrievalResult:
        merged = merge_with_rrf(
            vector_candidates=vector_candidates,
            keyword_candidates=keyword_candidates,
            vector_weight=vector_weight,
            rrf_k=rrf_k,
            exact_match_boost=exact_match_boost,
            exact_match_tokens=exact_match_tokens,
        )
        return HybridRetrievalResult(
            candidates=merged,
            vector_hit_count=len(vector_candidates),
            keyword_hit_count=len(keyword_candidates),
            exact_match_tokens=exact_match_tokens,
        )
