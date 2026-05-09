from app.services.confidence_service import ConfidenceChunkSignal, ConfidenceService


def test_confidence_service_returns_high_for_strong_retrieval_and_valid_citations() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=[
            ConfidenceChunkSignal(similarity_score=0.95, rerank_score=0.93),
            ConfidenceChunkSignal(similarity_score=0.91, rerank_score=0.90),
        ],
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
    )

    assert 0.0 <= result.score <= 1.0
    assert result.category == "high"
    assert result.explanation.citation_support_score > 0.9


def test_confidence_service_returns_medium_for_mixed_signals() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=[
            ConfidenceChunkSignal(similarity_score=0.70, rerank_score=0.65),
            ConfidenceChunkSignal(similarity_score=0.62, rerank_score=0.60),
        ],
        citation_count=1,
        citation_validation_score=0.75,
        not_found_signal=False,
    )

    assert 0.0 <= result.score <= 1.0
    assert result.category == "medium"


def test_confidence_service_returns_low_for_weak_retrieval() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=[
            ConfidenceChunkSignal(similarity_score=0.20, rerank_score=0.15),
            ConfidenceChunkSignal(similarity_score=0.17, rerank_score=0.13),
        ],
        citation_count=1,
        citation_validation_score=1.0,
        not_found_signal=False,
    )

    assert 0.0 <= result.score <= 1.0
    assert result.category == "low"


def test_confidence_service_handles_no_context() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=[],
        citation_count=0,
        citation_validation_score=1.0,
        not_found_signal=False,
    )

    assert result.score == 0.0
    assert result.category == "low"
    assert result.explanation.no_context is True


def test_confidence_service_penalizes_invalid_citations() -> None:
    service = ConfidenceService()

    strong_retrieval = service.score(
        chunks=[
            ConfidenceChunkSignal(similarity_score=0.92, rerank_score=0.90),
            ConfidenceChunkSignal(similarity_score=0.90, rerank_score=0.88),
        ],
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
    )

    invalid_citations = service.score(
        chunks=[
            ConfidenceChunkSignal(similarity_score=0.92, rerank_score=0.90),
            ConfidenceChunkSignal(similarity_score=0.90, rerank_score=0.88),
        ],
        citation_count=0,
        citation_validation_score=0.0,
        not_found_signal=False,
    )

    assert invalid_citations.score < strong_retrieval.score
    assert invalid_citations.category in {"low", "medium"}
