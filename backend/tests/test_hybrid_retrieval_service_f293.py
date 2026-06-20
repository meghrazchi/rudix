"""Unit tests for HybridRetrievalService and score merging — F293."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.domains.chat.services.hybrid_retrieval_service import (
    HybridRetrievalService,
    merge_with_rrf,
)
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievedCandidate
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vector_candidate(
    *,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    filename: str = "doc.pdf",
    text: str = "vector chunk text",
    similarity_score: float = 0.9,
) -> RetrievedCandidate:
    return RetrievedCandidate(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        filename=filename,
        page_number=1,
        text=text,
        similarity_score=similarity_score,
    )


def _keyword_candidate(
    *,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    filename: str = "doc.pdf",
    text: str = "keyword chunk text",
    keyword_score: float = 0.7,
    exact_match_hit: bool = False,
) -> KeywordRetrievedCandidate:
    return KeywordRetrievedCandidate(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        filename=filename,
        page_number=1,
        text=text,
        section_path=None,
        keyword_score=keyword_score,
        exact_match_hit=exact_match_hit,
    )


# ---------------------------------------------------------------------------
# merge_with_rrf
# ---------------------------------------------------------------------------


class TestMergeWithRRF:
    def test_empty_both_inputs(self) -> None:
        result = merge_with_rrf(
            vector_candidates=[],
            keyword_candidates=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result == []

    def test_vector_only(self) -> None:
        vc = _vector_candidate()
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert len(result) == 1
        assert result[0].chunk_id == vc.chunk_id
        assert result[0].retrieval_source == "vector"
        # keyword penalty = len(kw_candidates) + 1 = 0 + 1 = 1
        expected = 0.7 / (60 + 1) + 0.3 / (60 + 1)
        assert result[0].hybrid_score == pytest.approx(expected, abs=1e-9)

    def test_keyword_only(self) -> None:
        kc = _keyword_candidate()
        result = merge_with_rrf(
            vector_candidates=[],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert len(result) == 1
        assert result[0].chunk_id == kc.chunk_id
        assert result[0].retrieval_source == "keyword"
        # vector penalty = len(v_candidates) + 1 = 0 + 1 = 1
        expected = 0.7 / (60 + 1) + 0.3 / (60 + 1)
        assert result[0].hybrid_score == pytest.approx(expected, abs=1e-9)

    def test_chunk_in_both_sources_gets_hybrid_source(self) -> None:
        shared_id = uuid4()
        doc_id = uuid4()
        vc = _vector_candidate(chunk_id=shared_id, document_id=doc_id)
        kc = _keyword_candidate(chunk_id=shared_id, document_id=doc_id)
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert len(result) == 1
        assert result[0].retrieval_source == "hybrid"
        expected = 0.7 / (60 + 1) + 0.3 / (60 + 1)
        assert result[0].hybrid_score == pytest.approx(expected, abs=1e-9)

    def test_unique_chunks_from_each_source_both_appear(self) -> None:
        v_id = uuid4()
        k_id = uuid4()
        vc = _vector_candidate(chunk_id=v_id)
        kc = _keyword_candidate(chunk_id=k_id)
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert len(result) == 2
        chunk_ids = {str(r.chunk_id) for r in result}
        assert str(v_id) in chunk_ids
        assert str(k_id) in chunk_ids

    def test_results_sorted_by_hybrid_score_descending(self) -> None:
        ids = [uuid4() for _ in range(3)]
        vcs = [_vector_candidate(chunk_id=ids[i], similarity_score=0.9 - i * 0.1) for i in range(3)]
        result = merge_with_rrf(
            vector_candidates=vcs,
            keyword_candidates=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        scores = [r.hybrid_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_exact_match_boost_increases_score(self) -> None:
        chunk_id = uuid4()
        doc_id = uuid4()
        kc_exact = _keyword_candidate(
            chunk_id=chunk_id, document_id=doc_id, text="GDPR article 5", exact_match_hit=True
        )
        _keyword_candidate(text="general data text")

        result_boosted = merge_with_rrf(
            vector_candidates=[],
            keyword_candidates=[kc_exact],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=2.0,
            exact_match_tokens=["GDPR"],
        )
        result_unboosted = merge_with_rrf(
            vector_candidates=[],
            keyword_candidates=[kc_exact],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.0,
            exact_match_tokens=[],
        )

        assert result_boosted[0].hybrid_score > result_unboosted[0].hybrid_score

    def test_metadata_taken_from_vector_when_present(self) -> None:
        shared_id = uuid4()
        doc_id = uuid4()
        vc = _vector_candidate(
            chunk_id=shared_id,
            document_id=doc_id,
            filename="vector.pdf",
            text="vector text",
            similarity_score=0.95,
        )
        kc = _keyword_candidate(
            chunk_id=shared_id, document_id=doc_id, filename="keyword.pdf", text="keyword text"
        )
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result[0].filename == "vector.pdf"
        assert result[0].text == "vector text"
        assert result[0].similarity_score == pytest.approx(0.95)

    def test_keyword_score_preserved_on_hybrid_chunk(self) -> None:
        shared_id = uuid4()
        doc_id = uuid4()
        vc = _vector_candidate(chunk_id=shared_id, document_id=doc_id)
        kc = _keyword_candidate(chunk_id=shared_id, document_id=doc_id, keyword_score=0.88)
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result[0].keyword_score == pytest.approx(0.88)

    def test_vector_rank_and_keyword_rank_tracked(self) -> None:
        ids = [uuid4() for _ in range(2)]
        doc_ids = [uuid4() for _ in range(2)]
        vcs = [_vector_candidate(chunk_id=ids[i], document_id=doc_ids[i]) for i in range(2)]
        kcs = [_keyword_candidate(chunk_id=ids[i], document_id=doc_ids[i]) for i in range(2)]
        result = merge_with_rrf(
            vector_candidates=vcs,
            keyword_candidates=kcs,
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        for r in result:
            assert r.vector_rank is not None
            assert r.keyword_rank is not None

    def test_vector_rank_none_for_keyword_only_chunk(self) -> None:
        kc = _keyword_candidate()
        result = merge_with_rrf(
            vector_candidates=[],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result[0].vector_rank is None
        assert result[0].keyword_rank == 1


# ---------------------------------------------------------------------------
# HybridRetrievalService
# ---------------------------------------------------------------------------


class TestHybridRetrievalService:
    def test_merge_returns_correct_counts(self) -> None:
        ids = [uuid4() for _ in range(3)]
        doc_ids = [uuid4() for _ in range(3)]
        vcs = [_vector_candidate(chunk_id=ids[i], document_id=doc_ids[i]) for i in range(2)]
        kcs = [_keyword_candidate(chunk_id=ids[i], document_id=doc_ids[i]) for i in range(3)]

        service = HybridRetrievalService()
        result = service.merge(
            vector_candidates=vcs,
            keyword_candidates=kcs,
            exact_match_tokens=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
        )

        assert result.vector_hit_count == 2
        assert result.keyword_hit_count == 3
        assert len(result.candidates) == 3  # ids[0], ids[1], ids[2]

    def test_merge_passes_through_exact_match_tokens(self) -> None:
        service = HybridRetrievalService()
        result = service.merge(
            vector_candidates=[],
            keyword_candidates=[],
            exact_match_tokens=["GDPR", "SOC-2"],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
        )
        assert result.exact_match_tokens == ["GDPR", "SOC-2"]

    def test_merge_empty_inputs(self) -> None:
        service = HybridRetrievalService()
        result = service.merge(
            vector_candidates=[],
            keyword_candidates=[],
            exact_match_tokens=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
        )
        assert result.candidates == []
        assert result.vector_hit_count == 0
        assert result.keyword_hit_count == 0

    def test_merge_deduplicates_shared_chunk(self) -> None:
        shared_id = uuid4()
        doc_id = uuid4()
        vc = _vector_candidate(chunk_id=shared_id, document_id=doc_id)
        kc = _keyword_candidate(chunk_id=shared_id, document_id=doc_id)

        service = HybridRetrievalService()
        result = service.merge(
            vector_candidates=[vc],
            keyword_candidates=[kc],
            exact_match_tokens=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
        )
        assert len(result.candidates) == 1

    def test_rrf_k_parameter_affects_score(self) -> None:
        vc = _vector_candidate()
        service = HybridRetrievalService()

        result_k60 = service.merge(
            vector_candidates=[vc],
            keyword_candidates=[],
            exact_match_tokens=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.0,
        )
        result_k1 = service.merge(
            vector_candidates=[vc],
            keyword_candidates=[],
            exact_match_tokens=[],
            vector_weight=0.7,
            rrf_k=1,
            exact_match_boost=1.0,
        )

        # With smaller k, same rank gives higher score.
        assert result_k1.candidates[0].hybrid_score > result_k60.candidates[0].hybrid_score

    def test_vector_weight_zero_uses_only_keyword(self) -> None:
        shared_id = uuid4()
        doc_id = uuid4()
        vc = _vector_candidate(chunk_id=shared_id, document_id=doc_id)
        kc = _keyword_candidate(chunk_id=shared_id, document_id=doc_id)

        service = HybridRetrievalService()
        result = service.merge(
            vector_candidates=[vc],
            keyword_candidates=[kc],
            exact_match_tokens=[],
            vector_weight=0.0,
            rrf_k=60,
            exact_match_boost=1.0,
        )
        # vector_weight=0 → only keyword contributes to score
        expected = 0.0 / (60 + 1) + 1.0 / (60 + 1)
        assert result.candidates[0].hybrid_score == pytest.approx(expected, abs=1e-9)
