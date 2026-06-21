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
    no_context: bool
    not_found_signal: bool
    weights: dict[str, float]
    thresholds: dict[str, float]


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    category: str
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

    def score(
        self,
        *,
        chunks: list[ConfidenceChunkSignal],
        citation_count: int,
        citation_validation_score: float,
        not_found_signal: bool,
        citation_support_score_override: float | None = None,
    ) -> ConfidenceResult:
        if not chunks:
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
                no_context=True,
                not_found_signal=not_found_signal,
                weights={
                    "top_similarity": self._round(self.weights.top_similarity),
                    "average_similarity": self._round(self.weights.average_similarity),
                    "rerank_score": self._round(self.weights.rerank_score),
                    "citation_support": self._round(self.weights.citation_support),
                    "agreement": self._round(self.weights.agreement),
                },
                thresholds={
                    "medium": self._round(self.medium_threshold),
                    "high": self._round(self.high_threshold),
                },
            )
            return ConfidenceResult(score=0.0, category="low", explanation=explanation)

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

        raw_score = (
            (self.weights.top_similarity * top_similarity)
            + (self.weights.average_similarity * average_similarity)
            + (self.weights.rerank_score * top_rerank_score)
            + (self.weights.citation_support * citation_support_score)
            + (self.weights.agreement * retrieval_agreement_score)
        )

        citation_validation_multiplier = citation_validation
        penalty_multiplier = self.not_found_penalty_multiplier if not_found_signal else 1.0
        score = self._clamp(raw_score * citation_validation_multiplier * penalty_multiplier)

        explanation = ConfidenceExplanation(
            top_similarity=self._round(top_similarity),
            average_similarity=self._round(average_similarity),
            top_rerank_score=self._round(top_rerank_score),
            citation_support_score=self._round(citation_support_score),
            citation_validation_score=self._round(citation_validation),
            citation_coverage_score=self._round(citation_coverage_score),
            retrieval_agreement_score=self._round(retrieval_agreement_score),
            raw_score=self._round(self._clamp(raw_score)),
            citation_validation_multiplier=self._round(citation_validation_multiplier),
            not_found_penalty_multiplier=self._round(penalty_multiplier),
            no_context=False,
            not_found_signal=not_found_signal,
            weights={
                "top_similarity": self._round(self.weights.top_similarity),
                "average_similarity": self._round(self.weights.average_similarity),
                "rerank_score": self._round(self.weights.rerank_score),
                "citation_support": self._round(self.weights.citation_support),
                "agreement": self._round(self.weights.agreement),
            },
            thresholds={
                "medium": self._round(self.medium_threshold),
                "high": self._round(self.high_threshold),
            },
        )
        return ConfidenceResult(
            score=self._round(score),
            category=self._category(score),
            explanation=explanation,
        )
