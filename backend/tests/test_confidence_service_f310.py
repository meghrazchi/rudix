"""Deterministic tests for evidence-based confidence calibration (F310).

Covers: freshness multiplier, OCR quality multiplier, conflict multiplier,
graph evidence boost, trust level derivation, org-level threshold overrides,
explainability reasons, and no-double-counting of verification score.
"""

import pytest

from app.domains.chat.services.confidence_service import (
    ConfidenceChunkSignal,
    ConfidenceService,
)

_STRONG_CHUNKS = [
    ConfidenceChunkSignal(similarity_score=0.92, rerank_score=0.91),
    ConfidenceChunkSignal(similarity_score=0.90, rerank_score=0.88),
]
_MEDIUM_CHUNKS = [
    ConfidenceChunkSignal(similarity_score=0.68, rerank_score=0.65),
    ConfidenceChunkSignal(similarity_score=0.62, rerank_score=0.60),
]


# ── freshness multiplier ───────────────────────────────────────────────────────


def test_stale_sources_lower_confidence() -> None:
    service = ConfidenceService()

    fresh = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        freshness_multiplier=1.0,
    )
    stale = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        freshness_multiplier=0.80,
    )

    assert stale.score < fresh.score
    assert stale.explanation.freshness_multiplier == pytest.approx(0.80)


def test_full_freshness_does_not_change_score() -> None:
    service = ConfidenceService()

    base = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.9,
        not_found_signal=False,
    )
    with_fresh = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.9,
        not_found_signal=False,
        freshness_multiplier=1.0,
    )

    assert base.score == with_fresh.score


def test_freshness_multiplier_stored_in_explanation() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        freshness_multiplier=0.75,
    )

    assert result.explanation.freshness_multiplier == pytest.approx(0.75)


# ── OCR quality multiplier ─────────────────────────────────────────────────────


def test_low_ocr_quality_lowers_confidence() -> None:
    service = ConfidenceService()

    good_ocr = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        ocr_quality_multiplier=1.0,
    )
    bad_ocr = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        ocr_quality_multiplier=0.70,
    )

    assert bad_ocr.score < good_ocr.score
    assert bad_ocr.explanation.ocr_quality_multiplier == pytest.approx(0.70)


def test_failed_ocr_lowers_confidence_more_than_low_ocr() -> None:
    service = ConfidenceService()

    low_ocr = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        ocr_quality_multiplier=service.ocr_low_multiplier,
    )
    failed_ocr = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        ocr_quality_multiplier=service.ocr_failed_multiplier,
    )

    assert failed_ocr.score < low_ocr.score


# ── conflict multiplier ────────────────────────────────────────────────────────


def test_partial_conflict_lowers_confidence() -> None:
    service = ConfidenceService()

    no_conflict = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        conflict_multiplier=1.0,
    )
    partial_conflict = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        conflict_multiplier=1.0 - service.conflict_penalty_partial,
    )

    assert partial_conflict.score < no_conflict.score


def test_full_conflict_lowers_confidence_more_than_partial() -> None:
    service = ConfidenceService()

    partial = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        conflict_multiplier=1.0 - service.conflict_penalty_partial,
    )
    conflicting = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        conflict_multiplier=1.0 - service.conflict_penalty_conflicting,
    )

    assert conflicting.score < partial.score
    assert conflicting.explanation.conflict_multiplier < partial.explanation.conflict_multiplier


def test_conflict_multiplier_stored_in_explanation() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.9,
        not_found_signal=False,
        conflict_multiplier=0.85,
    )

    assert result.explanation.conflict_multiplier == pytest.approx(0.85)


# ── graph evidence boost ───────────────────────────────────────────────────────


def test_graph_evidence_boosts_confidence() -> None:
    service = ConfidenceService()

    no_graph = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.9,
        not_found_signal=False,
        graph_context_used=False,
    )
    with_graph = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.9,
        not_found_signal=False,
        graph_context_used=True,
    )

    assert with_graph.score > no_graph.score
    assert with_graph.explanation.graph_evidence_boost == pytest.approx(service.graph_evidence_boost)


def test_graph_evidence_boost_zero_when_not_used() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.9,
        not_found_signal=False,
        graph_context_used=False,
    )

    assert result.explanation.graph_evidence_boost == 0.0


# ── trust levels ───────────────────────────────────────────────────────────────


def test_trust_level_high_for_strong_unambiguous_answer() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
    )

    assert result.trust_level == "high"
    assert result.explanation.trust_level == "high"


def test_trust_level_not_found_when_signal_set() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=[],
        citation_count=0,
        citation_validation_score=1.0,
        not_found_signal=True,
    )

    assert result.trust_level == "not_found"
    assert result.explanation.trust_level == "not_found"


def test_trust_level_warning_when_stale_sources_and_low_score() -> None:
    service = ConfidenceService(medium_threshold=0.50)

    result = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=0,
        citation_validation_score=0.4,
        not_found_signal=False,
        freshness_multiplier=0.70,  # heavily stale → triggers warning
    )

    # Score should be below medium threshold, and freshness degraded → "warning"
    assert result.score < 0.50
    assert result.trust_level == "warning"


def test_trust_level_warning_when_conflict_and_low_score() -> None:
    service = ConfidenceService(medium_threshold=0.50)

    result = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=0,
        citation_validation_score=0.4,
        not_found_signal=False,
        conflict_multiplier=0.80,  # conflict → triggers warning
    )

    assert result.score < 0.50
    assert result.trust_level == "warning"


def test_trust_level_warning_when_low_ocr_and_low_score() -> None:
    service = ConfidenceService(medium_threshold=0.50)

    result = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=0,
        citation_validation_score=0.4,
        not_found_signal=False,
        ocr_quality_multiplier=0.70,  # low OCR → triggers warning
    )

    assert result.score < 0.50
    assert result.trust_level == "warning"


def test_trust_level_low_not_warning_when_no_quality_signals() -> None:
    service = ConfidenceService(medium_threshold=0.50)

    result = service.score(
        chunks=[ConfidenceChunkSignal(similarity_score=0.30)],
        citation_count=0,
        citation_validation_score=0.3,
        not_found_signal=False,
        freshness_multiplier=1.0,
        ocr_quality_multiplier=1.0,
        conflict_multiplier=1.0,
    )

    assert result.trust_level == "low"


# ── explainability reasons ─────────────────────────────────────────────────────


def test_no_context_reason_returned_when_chunks_empty() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=[],
        citation_count=0,
        citation_validation_score=1.0,
        not_found_signal=False,
    )

    codes = [r.code for r in result.explanation.reasons]
    assert "no_context" in codes
    assert len(result.explanation.reasons) == 1


def test_stale_sources_reason_emitted_when_freshness_degraded() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        freshness_multiplier=0.80,
    )

    codes = [r.code for r in result.explanation.reasons]
    assert "stale_sources" in codes
    stale_reason = next(r for r in result.explanation.reasons if r.code == "stale_sources")
    assert stale_reason.impact == "negative"
    assert stale_reason.magnitude == pytest.approx(0.20, abs=1e-3)


def test_low_ocr_reason_emitted_when_ocr_degraded() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        ocr_quality_multiplier=0.75,
    )

    codes = [r.code for r in result.explanation.reasons]
    assert "low_ocr_quality" in codes


def test_source_conflict_reason_emitted_when_conflict_multiplier_below_one() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        conflict_multiplier=0.85,
    )

    codes = [r.code for r in result.explanation.reasons]
    assert "source_conflict" in codes


def test_graph_evidence_reason_emitted_when_graph_used() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        graph_context_used=True,
    )

    codes = [r.code for r in result.explanation.reasons]
    assert "graph_evidence" in codes
    graph_reason = next(r for r in result.explanation.reasons if r.code == "graph_evidence")
    assert graph_reason.impact == "positive"


def test_strong_retrieval_reason_emitted_for_high_similarity() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
    )

    codes = [r.code for r in result.explanation.reasons]
    assert "strong_retrieval" in codes


def test_reasons_are_deterministic_for_same_inputs() -> None:
    service = ConfidenceService()

    r1 = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.6,
        not_found_signal=False,
        freshness_multiplier=0.80,
        conflict_multiplier=0.90,
    )
    r2 = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.6,
        not_found_signal=False,
        freshness_multiplier=0.80,
        conflict_multiplier=0.90,
    )

    assert r1.explanation.reasons == r2.explanation.reasons
    assert r1.score == r2.score


# ── org-level threshold overrides ─────────────────────────────────────────────


def test_org_high_threshold_override_changes_category() -> None:
    service = ConfidenceService(high_threshold=0.80)

    # Score is high under default settings (≥0.80)
    default_result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
    )
    # Raise org threshold so same score becomes medium
    org_result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        high_threshold_override=0.99,
    )

    assert default_result.category == "high"
    assert org_result.category == "medium"
    assert org_result.trust_level == "medium"


def test_org_medium_threshold_override_changes_category() -> None:
    service = ConfidenceService()

    # Medium chunks should be "medium" with default 0.50 threshold
    default_result = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.75,
        not_found_signal=False,
    )
    # Raise org medium threshold so score falls below → "low"
    org_result = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.75,
        not_found_signal=False,
        medium_threshold_override=0.95,
    )

    assert default_result.category == "medium"
    assert org_result.category == "low"


# ── verification score passthrough ────────────────────────────────────────────


def test_verification_support_score_stored_in_explanation_not_double_counted() -> None:
    service = ConfidenceService()

    without_vs = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        citation_support_score_override=0.90,
        not_found_signal=False,
    )
    with_vs = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        citation_support_score_override=0.90,
        not_found_signal=False,
        verification_support_score=0.90,
    )

    # Score must not change when only verification_support_score is added
    assert without_vs.score == with_vs.score
    # But the explanation carries the value for display
    assert with_vs.explanation.verification_support_score == pytest.approx(0.90)
    assert without_vs.explanation.verification_support_score is None


# ── combined signal interactions ───────────────────────────────────────────────


def test_combined_degraded_signals_multiply() -> None:
    service = ConfidenceService()

    fresh_no_ocr = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        freshness_multiplier=0.80,
        ocr_quality_multiplier=1.0,
    )
    fresh_with_ocr = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        freshness_multiplier=0.80,
        ocr_quality_multiplier=0.80,
    )

    # Both penalties should stack multiplicatively
    assert fresh_with_ocr.score < fresh_no_ocr.score


def test_graph_boost_partially_offsets_stale_penalty() -> None:
    service = ConfidenceService()

    stale_no_graph = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.9,
        not_found_signal=False,
        freshness_multiplier=0.80,
        graph_context_used=False,
    )
    stale_with_graph = service.score(
        chunks=_MEDIUM_CHUNKS,
        citation_count=1,
        citation_validation_score=0.9,
        not_found_signal=False,
        freshness_multiplier=0.80,
        graph_context_used=True,
    )

    assert stale_with_graph.score > stale_no_graph.score


def test_score_is_clamped_to_zero_one_with_extreme_multipliers() -> None:
    service = ConfidenceService()

    result = service.score(
        chunks=_STRONG_CHUNKS,
        citation_count=2,
        citation_validation_score=1.0,
        not_found_signal=False,
        freshness_multiplier=0.0,
        ocr_quality_multiplier=0.0,
        conflict_multiplier=0.0,
    )

    assert result.score == pytest.approx(0.0)
    assert 0.0 <= result.score <= 1.0
