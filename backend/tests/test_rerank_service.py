import pytest

from app.services.rerank_service import RerankCandidate, RerankService


def test_rerank_disabled_returns_similarity_order_without_rerank_fields() -> None:
    service = RerankService(mmr_lambda=0.7, candidate_count=10, duplicate_similarity_threshold=0.9)
    candidates = [
        RerankCandidate(key="b", text="second text", similarity_score=0.82),
        RerankCandidate(key="a", text="first text", similarity_score=0.91),
        RerankCandidate(key="c", text="third text", similarity_score=0.77),
    ]

    ranked = service.rerank(candidates=candidates, enabled=False, final_top_k=2)

    assert [item.key for item in ranked] == ["a", "b"]
    assert all(item.rerank_score is None for item in ranked)
    assert all(item.rerank_rank is None for item in ranked)


def test_rerank_mmr_prefers_diversity_when_near_duplicates_exist() -> None:
    service = RerankService(mmr_lambda=0.7, candidate_count=10, duplicate_similarity_threshold=0.8)
    candidates = [
        RerankCandidate(
            key="a",
            text="employees receive twenty annual leave days and medical benefits",
            similarity_score=0.95,
        ),
        RerankCandidate(
            key="b",
            text="employees receive twenty annual leave days and medical benefit details",
            similarity_score=0.94,
        ),
        RerankCandidate(
            key="c",
            text="remote work policy includes laptop support and internet stipend",
            similarity_score=0.87,
        ),
    ]

    ranked = service.rerank(candidates=candidates, enabled=True, final_top_k=2)

    assert [item.key for item in ranked] == ["a", "c"]
    assert ranked[0].rerank_rank == 1
    assert ranked[1].rerank_rank == 2
    assert ranked[0].rerank_score is not None
    assert ranked[1].rerank_score is not None
    assert ranked[0].similarity_score == pytest.approx(0.95)
    assert ranked[1].similarity_score == pytest.approx(0.87)


def test_rerank_duplicate_fallback_still_returns_top_k_when_needed() -> None:
    service = RerankService(mmr_lambda=0.5, candidate_count=10, duplicate_similarity_threshold=0.2)
    candidates = [
        RerankCandidate(
            key="a",
            text="policy leave entitlement summary",
            similarity_score=0.9,
        ),
        RerankCandidate(
            key="b",
            text="policy leave entitlement summary",
            similarity_score=0.89,
        ),
    ]

    ranked = service.rerank(candidates=candidates, enabled=True, final_top_k=2)

    assert len(ranked) == 2
    assert [item.key for item in ranked] == ["a", "b"]
