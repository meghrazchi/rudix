from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from app.core.config import settings


@dataclass(frozen=True)
class ConfidenceChunkSignal:
    similarity_score: float
    rerank_score: float | None = None


@dataclass(frozen=True)
class ConfidenceWeights:
    top_similarity: float
    average_similarity: float
    rerank_score: float
    citation_support: float
    agreement: float


@dataclass(frozen=True)
class ConfidenceReason:
    """Single explainable signal that contributed to the confidence score."""

    code: str
    label: str
    impact: str  # "positive" | "negative" | "neutral"
    magnitude: float  # 0.0–1.0 size of the effect


@dataclass(frozen=True)
class ConfidenceExplanation:
    top_similarity: float
    average_similarity: float
    top_rerank_score: float
    citation_support_score: float
    citation_validation_score: float
    citation_coverage_score: float
    retrieval_agreement_score: float
    raw_score: float
    citation_validation_multiplier: float
    not_found_penalty_multiplier: float
    freshness_multiplier: float
    ocr_quality_multiplier: float
    conflict_multiplier: float
    graph_evidence_boost: float
    verification_support_score: float | None
    no_context: bool
    not_found_signal: bool
    trust_level: str
    reasons: tuple[ConfidenceReason, ...]
    weights: dict[str, float]
    thresholds: dict[str, float]


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    category: str
    trust_level: str
    explanation: ConfidenceExplanation


class ConfidenceService:
    def __init__(
        self,
        *,
        weights: ConfidenceWeights | None = None,
        medium_threshold: float | None = None,
        high_threshold: float | None = None,
        not_found_penalty_multiplier: float | None = None,
        citation_coverage_target: int | None = None,
        graph_evidence_boost: float | None = None,
        freshness_stale_penalty: float | None = None,
        conflict_penalty_partial: float | None = None,
        conflict_penalty_conflicting: float | None = None,
        ocr_medium_multiplier: float | None = None,
        ocr_low_multiplier: float | None = None,
        ocr_failed_multiplier: float | None = None,
        warning_threshold: float | None = None,
    ) -> None:
        configured_weights = weights or ConfidenceWeights(
            top_similarity=settings.confidence_weight_top_similarity,
            average_similarity=settings.confidence_weight_average_similarity,
            rerank_score=settings.confidence_weight_rerank_score,
            citation_support=settings.confidence_weight_citation_support,
            agreement=settings.confidence_weight_agreement,
        )
        self.weights = self._normalize_weights(configured_weights)
        self.medium_threshold = (
            medium_threshold
            if medium_threshold is not None
            else settings.confidence_medium_threshold
        )
        self.high_threshold = (
            high_threshold if high_threshold is not None else settings.confidence_high_threshold
        )
        self.not_found_penalty_multiplier = (
            not_found_penalty_multiplier
            if not_found_penalty_multiplier is not None
            else settings.confidence_not_found_penalty_multiplier
        )
        self.citation_coverage_target = (
            citation_coverage_target
            if citation_coverage_target is not None
            else settings.confidence_citation_coverage_target
        )
        self.graph_evidence_boost = (
            graph_evidence_boost
            if graph_evidence_boost is not None
            else settings.confidence_graph_evidence_boost
        )
        self.freshness_stale_penalty = (
            freshness_stale_penalty
            if freshness_stale_penalty is not None
            else settings.confidence_freshness_stale_penalty
        )
        self.conflict_penalty_partial = (
            conflict_penalty_partial
            if conflict_penalty_partial is not None
            else settings.confidence_conflict_penalty_partial
        )
        self.conflict_penalty_conflicting = (
            conflict_penalty_conflicting
            if conflict_penalty_conflicting is not None
            else settings.confidence_conflict_penalty_conflicting
        )
        self.ocr_medium_multiplier = (
            ocr_medium_multiplier
            if ocr_medium_multiplier is not None
            else settings.confidence_ocr_medium_multiplier
        )
        self.ocr_low_multiplier = (
            ocr_low_multiplier
            if ocr_low_multiplier is not None
            else settings.confidence_ocr_low_multiplier
        )
        self.ocr_failed_multiplier = (
            ocr_failed_multiplier
            if ocr_failed_multiplier is not None
            else settings.confidence_ocr_failed_multiplier
        )
        self.warning_threshold = (
            warning_threshold
            if warning_threshold is not None
            else settings.confidence_warning_threshold
        )

    @staticmethod
    def _normalize_weights(weights: ConfidenceWeights) -> ConfidenceWeights:
        total = (
            weights.top_similarity
            + weights.average_similarity
            + weights.rerank_score
            + weights.citation_support
            + weights.agreement
        )
        if total <= 0:
            raise ValueError("confidence weights sum must be > 0")
        return ConfidenceWeights(
            top_similarity=weights.top_similarity / total,
            average_similarity=weights.average_similarity / total,
            rerank_score=weights.rerank_score / total,
            citation_support=weights.citation_support / total,
            agreement=weights.agreement / total,
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _round(value: float) -> float:
        return round(value, 4)

    def _category(self, score: float) -> str:
        if score >= self.high_threshold:
            return "high"
        if score >= self.medium_threshold:
            return "medium"
        return "low"

    def _trust_level(
        self,
        score: float,
        *,
        not_found_signal: bool,
        freshness_multiplier: float,
        ocr_quality_multiplier: float,
        conflict_multiplier: float,
    ) -> str:
        """Derive trust level from score and quality-signal degradation.

        "warning" is emitted when the score falls below the medium threshold
        and a quality signal (freshness, OCR, or source conflict) materially
        degraded the result — distinguishing quality-driven low confidence
        from simply weak retrieval.
        """
        if not_found_signal:
            return "not_found"
        if score >= self.high_threshold:
            return "high"
        if score >= self.medium_threshold:
            return "medium"
        # Below medium — flag "warning" when quality signals are degraded
        quality_degraded = (
            freshness_multiplier < 0.85
            or ocr_quality_multiplier < 0.80
            or conflict_multiplier < 0.85
        )
        if quality_degraded:
            return "warning"
        return "low"

    def _agreement_score(self, chunks: list[ConfidenceChunkSignal]) -> tuple[float, float]:
        similarities = [self._clamp(chunk.similarity_score) for chunk in chunks]
        avg_similarity = mean(similarities)
        avg_abs_deviation = mean(abs(score - avg_similarity) for score in similarities)
        cohesion_score = self._clamp(1 - (avg_abs_deviation / 0.5))

        top_similarity = similarities[0]
        top_rerank = chunks[0].rerank_score
        if top_rerank is None:
            alignment_score = 1.0
            top_rerank_score = top_similarity
        else:
            top_rerank_score = self._clamp(top_rerank)
            alignment_score = self._clamp(1 - abs(top_similarity - top_rerank_score))

        return self._clamp((cohesion_score + alignment_score) / 2), top_rerank_score

    def _build_reasons(
        self,
        *,
        top_similarity: float,
        citation_support_score: float,
        retrieval_agreement_score: float,
        freshness_multiplier: float,
        ocr_quality_multiplier: float,
        conflict_multiplier: float,
        graph_context_used: bool,
        graph_evidence_boost: float,
        not_found_signal: bool,
        citation_validation_multiplier: float,
        no_context: bool,
    ) -> tuple[ConfidenceReason, ...]:
        reasons: list[ConfidenceReason] = []

        if no_context:
            reasons.append(
                ConfidenceReason(
                    code="no_context",
                    label="No relevant content found in knowledge base",
                    impact="negative",
                    magnitude=1.0,
                )
            )
            return tuple(reasons)

        if not_found_signal:
            reasons.append(
                ConfidenceReason(
                    code="not_found",
                    label="Answer not found in available sources",
                    impact="negative",
                    magnitude=self._round(1.0 - self.not_found_penalty_multiplier),
                )
            )

        if top_similarity >= 0.85:
            reasons.append(
                ConfidenceReason(
                    code="strong_retrieval",
                    label="Strong semantic match with knowledge base",
                    impact="positive",
                    magnitude=self._round(top_similarity),
                )
            )
        elif top_similarity < 0.50:
            reasons.append(
                ConfidenceReason(
                    code="weak_retrieval",
                    label="Weak semantic match — answer may not be well grounded",
                    impact="negative",
                    magnitude=self._round(1.0 - top_similarity),
                )
            )

        if citation_support_score >= 0.80:
            reasons.append(
                ConfidenceReason(
                    code="strong_citation_support",
                    label="Citations strongly support the answer",
                    impact="positive",
                    magnitude=self._round(citation_support_score),
                )
            )
        elif citation_support_score < 0.50:
            reasons.append(
                ConfidenceReason(
                    code="weak_citation_support",
                    label="Citations provide limited support for the answer",
                    impact="negative",
                    magnitude=self._round(1.0 - citation_support_score),
                )
            )

        if retrieval_agreement_score < 0.60:
            reasons.append(
                ConfidenceReason(
                    code="low_source_agreement",
                    label="Retrieved sources show low mutual agreement",
                    impact="negative",
                    magnitude=self._round(1.0 - retrieval_agreement_score),
                )
            )

        if freshness_multiplier < 1.0:
            reasons.append(
                ConfidenceReason(
                    code="stale_sources",
                    label="Some cited sources may be outdated",
                    impact="negative",
                    magnitude=self._round(1.0 - freshness_multiplier),
                )
            )

        if ocr_quality_multiplier < 1.0:
            reasons.append(
                ConfidenceReason(
                    code="low_ocr_quality",
                    label="Some source documents have reduced OCR extraction quality",
                    impact="negative",
                    magnitude=self._round(1.0 - ocr_quality_multiplier),
                )
            )

        if conflict_multiplier < 1.0:
            reasons.append(
                ConfidenceReason(
                    code="source_conflict",
                    label="Sources contain conflicting information",
                    impact="negative",
                    magnitude=self._round(1.0 - conflict_multiplier),
                )
            )

        if graph_context_used and graph_evidence_boost > 0:
            reasons.append(
                ConfidenceReason(
                    code="graph_evidence",
                    label="Knowledge graph evidence strengthens the answer",
                    impact="positive",
                    magnitude=self._round(graph_evidence_boost),
                )
            )

        if citation_validation_multiplier < 0.90:
            reasons.append(
                ConfidenceReason(
                    code="citation_validation_issues",
                    label="Some citations could not be fully validated",
                    impact="negative",
                    magnitude=self._round(1.0 - citation_validation_multiplier),
                )
            )

        return tuple(reasons)

    def score(
        self,
        *,
        chunks: list[ConfidenceChunkSignal],
        citation_count: int,
        citation_validation_score: float,
        not_found_signal: bool,
        citation_support_score_override: float | None = None,
        freshness_multiplier: float = 1.0,
        ocr_quality_multiplier: float = 1.0,
        conflict_multiplier: float = 1.0,
        graph_context_used: bool = False,
        verification_support_score: float | None = None,
        high_threshold_override: float | None = None,
        medium_threshold_override: float | None = None,
    ) -> ConfidenceResult:
        """Score answer confidence from measurable retrieval and quality signals.

        New signals (F310):
        - freshness_multiplier: pre-computed from source trust status; <1.0 for stale sources
        - ocr_quality_multiplier: pre-computed from OCR quality across citations; <1.0 for degraded OCR
        - conflict_multiplier: pre-computed from conflict detection; <1.0 when sources disagree
        - graph_context_used: adds a small additive boost when graph evidence was incorporated
        - verification_support_score: captured for explainability; already baked into
          citation_support_score_override when grounded verification ran, so NOT double-counted
        - high_threshold_override / medium_threshold_override: org-level threshold overrides
        """
        effective_high = (
            high_threshold_override if high_threshold_override is not None else self.high_threshold
        )
        effective_medium = (
            medium_threshold_override
            if medium_threshold_override is not None
            else self.medium_threshold
        )
        freshness_m = self._clamp(freshness_multiplier)
        ocr_m = self._clamp(ocr_quality_multiplier)
        conflict_m = self._clamp(conflict_multiplier)
        graph_boost = self.graph_evidence_boost if graph_context_used else 0.0

        def _resolve_category(s: float) -> str:
            if s >= effective_high:
                return "high"
            if s >= effective_medium:
                return "medium"
            return "low"

        def _resolve_trust_level(s: float) -> str:
            if not_found_signal:
                return "not_found"
            if s >= effective_high:
                return "high"
            if s >= effective_medium:
                return "medium"
            quality_degraded = freshness_m < 0.85 or ocr_m < 0.80 or conflict_m < 0.85
            return "warning" if quality_degraded else "low"

        if not chunks:
            reasons = self._build_reasons(
                top_similarity=0.0,
                citation_support_score=0.0,
                retrieval_agreement_score=0.0,
                freshness_multiplier=freshness_m,
                ocr_quality_multiplier=ocr_m,
                conflict_multiplier=conflict_m,
                graph_context_used=graph_context_used,
                graph_evidence_boost=graph_boost,
                not_found_signal=not_found_signal,
                citation_validation_multiplier=1.0,
                no_context=True,
            )
            explanation = ConfidenceExplanation(
                top_similarity=0.0,
                average_similarity=0.0,
                top_rerank_score=0.0,
                citation_support_score=0.0,
                citation_validation_score=self._clamp(citation_validation_score),
                citation_coverage_score=0.0,
                retrieval_agreement_score=0.0,
                raw_score=0.0,
                citation_validation_multiplier=1.0,
                not_found_penalty_multiplier=1.0,
                freshness_multiplier=freshness_m,
                ocr_quality_multiplier=ocr_m,
                conflict_multiplier=conflict_m,
                graph_evidence_boost=graph_boost,
                verification_support_score=verification_support_score,
                no_context=True,
                not_found_signal=not_found_signal,
                trust_level=_resolve_trust_level(0.0),
                reasons=reasons,
                weights={
                    "top_similarity": self._round(self.weights.top_similarity),
                    "average_similarity": self._round(self.weights.average_similarity),
                    "rerank_score": self._round(self.weights.rerank_score),
                    "citation_support": self._round(self.weights.citation_support),
                    "agreement": self._round(self.weights.agreement),
                },
                thresholds={
                    "medium": self._round(effective_medium),
                    "high": self._round(effective_high),
                },
            )
            return ConfidenceResult(
                score=0.0,
                category="low",
                trust_level=_resolve_trust_level(0.0),
                explanation=explanation,
            )

        similarities = [self._clamp(chunk.similarity_score) for chunk in chunks]
        top_similarity = similarities[0]
        average_similarity = self._clamp(mean(similarities))
        retrieval_agreement_score, top_rerank_score = self._agreement_score(chunks)

        citation_validation = self._clamp(citation_validation_score)
        coverage_denominator = max(1, min(self.citation_coverage_target, len(chunks)))
        citation_coverage_score = self._clamp(citation_count / coverage_denominator)
        if citation_support_score_override is None:
            citation_support_score = self._clamp(
                (citation_validation + citation_coverage_score) / 2
            )
        else:
            citation_support_score = self._clamp(citation_support_score_override)

        raw_score_base = (
            (self.weights.top_similarity * top_similarity)
            + (self.weights.average_similarity * average_similarity)
            + (self.weights.rerank_score * top_rerank_score)
            + (self.weights.citation_support * citation_support_score)
            + (self.weights.agreement * retrieval_agreement_score)
        )
        raw_score = self._clamp(raw_score_base + graph_boost)

        citation_validation_multiplier = citation_validation
        penalty_multiplier = self.not_found_penalty_multiplier if not_found_signal else 1.0
        score = self._clamp(
            raw_score
            * freshness_m
            * ocr_m
            * conflict_m
            * citation_validation_multiplier
            * penalty_multiplier
        )

        trust_level = _resolve_trust_level(score)
        reasons = self._build_reasons(
            top_similarity=top_similarity,
            citation_support_score=citation_support_score,
            retrieval_agreement_score=retrieval_agreement_score,
            freshness_multiplier=freshness_m,
            ocr_quality_multiplier=ocr_m,
            conflict_multiplier=conflict_m,
            graph_context_used=graph_context_used,
            graph_evidence_boost=graph_boost,
            not_found_signal=not_found_signal,
            citation_validation_multiplier=citation_validation_multiplier,
            no_context=False,
        )

        explanation = ConfidenceExplanation(
            top_similarity=self._round(top_similarity),
            average_similarity=self._round(average_similarity),
            top_rerank_score=self._round(top_rerank_score),
            citation_support_score=self._round(citation_support_score),
            citation_validation_score=self._round(citation_validation),
            citation_coverage_score=self._round(citation_coverage_score),
            retrieval_agreement_score=self._round(retrieval_agreement_score),
            raw_score=self._round(self._clamp(raw_score_base)),
            citation_validation_multiplier=self._round(citation_validation_multiplier),
            not_found_penalty_multiplier=self._round(penalty_multiplier),
            freshness_multiplier=self._round(freshness_m),
            ocr_quality_multiplier=self._round(ocr_m),
            conflict_multiplier=self._round(conflict_m),
            graph_evidence_boost=self._round(graph_boost),
            verification_support_score=verification_support_score,
            no_context=False,
            not_found_signal=not_found_signal,
            trust_level=trust_level,
            reasons=reasons,
            weights={
                "top_similarity": self._round(self.weights.top_similarity),
                "average_similarity": self._round(self.weights.average_similarity),
                "rerank_score": self._round(self.weights.rerank_score),
                "citation_support": self._round(self.weights.citation_support),
                "agreement": self._round(self.weights.agreement),
            },
            thresholds={
                "medium": self._round(effective_medium),
                "high": self._round(effective_high),
            },
        )
        return ConfidenceResult(
            score=self._round(score),
            category=_resolve_category(score),
            trust_level=trust_level,
            explanation=explanation,
        )
