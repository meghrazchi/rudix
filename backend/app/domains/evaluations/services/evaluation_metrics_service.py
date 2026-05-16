from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from statistics import mean
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class EvaluationMetricOptions:
    faithfulness_enabled: bool = False
    answer_relevance_enabled: bool = False
    judge_provider: str = "llm_judge"
    judge_model_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievedMetricChunk:
    document_id: UUID
    page_number: int | None


@dataclass(frozen=True)
class EvaluationJudgeScores:
    faithfulness_score: float | None
    answer_relevance_score: float | None
    provider: str


@dataclass(frozen=True)
class EvaluationQuestionMetrics:
    retrieval_hit_rate: float | None
    context_precision: float | None
    context_recall: float | None
    faithfulness_score: float | None
    answer_relevance_score: float | None
    citation_accuracy_score: float | None
    refusal_accuracy: float | None
    latency_ms: int
    cost_usd: float
    token_input_count: int
    token_output_count: int
    judge_used: bool
    judge_provider: str | None
    judge_error: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvaluationMetricsService:
    """Computes per-question and per-run evaluation metrics."""

    @staticmethod
    def _normalize_bool(value: object, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, float):
            return value != 0.0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "t", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "f", "no", "n", "off"}:
                return False
        return default

    @staticmethod
    def _normalize_metric_option_string(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_expected_answer(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.lower().split()).strip()

    @staticmethod
    def _clamp_score(value: float | None) -> float | None:
        if value is None:
            return None
        return max(0.0, min(1.0, round(float(value), 4)))

    @staticmethod
    def parse_metric_options(raw_options: dict[str, object]) -> EvaluationMetricOptions:
        faithfulness_enabled = EvaluationMetricsService._normalize_bool(
            raw_options.get("faithfulness"),
            default=False,
        )
        answer_relevance_enabled = EvaluationMetricsService._normalize_bool(
            raw_options.get("answer_relevance"),
            default=False,
        )
        provider = (
            EvaluationMetricsService._normalize_metric_option_string(raw_options.get("judge_provider"))
            or "llm_judge"
        )
        judge_model_name = (
            EvaluationMetricsService._normalize_metric_option_string(raw_options.get("judge_model_name"))
            or EvaluationMetricsService._normalize_metric_option_string(raw_options.get("model_name"))
        )
        return EvaluationMetricOptions(
            faithfulness_enabled=faithfulness_enabled,
            answer_relevance_enabled=answer_relevance_enabled,
            judge_provider=provider,
            judge_model_name=judge_model_name,
        )

    def _expected_reference_relevant_count(
        self,
        *,
        retrieved_chunks: list[RetrievedMetricChunk],
        expected_document_id: UUID | None,
        expected_page_number: int | None,
    ) -> tuple[int, bool]:
        has_expected_reference = expected_document_id is not None or expected_page_number is not None
        if not has_expected_reference:
            return 0, False
        relevant = 0
        for chunk in retrieved_chunks:
            if expected_document_id is not None and chunk.document_id != expected_document_id:
                continue
            if expected_page_number is not None and chunk.page_number != expected_page_number:
                continue
            relevant += 1
        return relevant, True

    def _heuristic_answer_relevance_score(
        self,
        *,
        generated_answer: str,
        expected_answer: str | None,
        not_found: bool,
    ) -> float:
        if expected_answer is None:
            return 1.0 if not_found else 0.2
        if not_found:
            return 0.0
        similarity = SequenceMatcher(
            a=self._normalize_text(generated_answer),
            b=self._normalize_text(expected_answer),
        ).ratio()
        return float(similarity)

    def _heuristic_faithfulness_score(
        self,
        *,
        not_found: bool,
        citation_accuracy_score: float | None,
        citation_count: int,
        selected_chunk_count: int,
        retrieval_hit_rate: float | None,
        expected_answer: str | None,
    ) -> float:
        if not_found:
            return 1.0 if expected_answer is None else 0.0
        citation_accuracy = citation_accuracy_score if citation_accuracy_score is not None else 0.0
        coverage_denominator = max(1, min(2, selected_chunk_count))
        coverage = min(1.0, citation_count / coverage_denominator)
        retrieval_signal = retrieval_hit_rate if retrieval_hit_rate is not None else (1.0 if selected_chunk_count > 0 else 0.0)
        return (0.55 * citation_accuracy) + (0.25 * coverage) + (0.20 * retrieval_signal)

    def score_question(
        self,
        *,
        expected_document_id: UUID | None,
        expected_page_number: int | None,
        expected_answer: str | None,
        generated_answer: str,
        not_found: bool,
        retrieved_chunks: list[RetrievedMetricChunk],
        selected_chunk_count: int,
        citation_count: int,
        citation_accuracy_score: float | None,
        latency_ms: int,
        cost_usd: float | Decimal | None,
        token_input_count: int,
        token_output_count: int,
        options: EvaluationMetricOptions,
        judge_scores: EvaluationJudgeScores | None = None,
        judge_error: str | None = None,
    ) -> EvaluationQuestionMetrics:
        normalized_expected_answer = self._normalize_expected_answer(expected_answer)
        relevant_retrieved_count, has_expected_reference = self._expected_reference_relevant_count(
            retrieved_chunks=retrieved_chunks,
            expected_document_id=expected_document_id,
            expected_page_number=expected_page_number,
        )
        retrieval_hit_rate: float | None = None
        context_precision: float | None = None
        context_recall: float | None = None
        if has_expected_reference:
            retrieval_hit_rate = 1.0 if relevant_retrieved_count > 0 else 0.0
            retrieved_count = len(retrieved_chunks)
            context_precision = (
                0.0 if retrieved_count == 0 else float(relevant_retrieved_count / retrieved_count)
            )
            # Current schema carries one expected source reference.
            context_recall = 1.0 if relevant_retrieved_count > 0 else 0.0

        refusal_accuracy: float | None = None
        if normalized_expected_answer is None:
            refusal_accuracy = 1.0 if not_found else 0.0

        heuristic_faithfulness = self._heuristic_faithfulness_score(
            not_found=not_found,
            citation_accuracy_score=citation_accuracy_score,
            citation_count=citation_count,
            selected_chunk_count=selected_chunk_count,
            retrieval_hit_rate=retrieval_hit_rate,
            expected_answer=normalized_expected_answer,
        )
        heuristic_answer_relevance = self._heuristic_answer_relevance_score(
            generated_answer=generated_answer,
            expected_answer=normalized_expected_answer,
            not_found=not_found,
        )

        faithfulness_score = heuristic_faithfulness
        answer_relevance_score = heuristic_answer_relevance
        judge_used = False
        judge_provider: str | None = None
        if judge_scores is not None:
            judge_provider = judge_scores.provider
            if options.faithfulness_enabled and judge_scores.faithfulness_score is not None:
                faithfulness_score = judge_scores.faithfulness_score
                judge_used = True
            if options.answer_relevance_enabled and judge_scores.answer_relevance_score is not None:
                answer_relevance_score = judge_scores.answer_relevance_score
                judge_used = True

        return EvaluationQuestionMetrics(
            retrieval_hit_rate=self._clamp_score(retrieval_hit_rate),
            context_precision=self._clamp_score(context_precision),
            context_recall=self._clamp_score(context_recall),
            faithfulness_score=self._clamp_score(faithfulness_score),
            answer_relevance_score=self._clamp_score(answer_relevance_score),
            citation_accuracy_score=self._clamp_score(citation_accuracy_score),
            refusal_accuracy=self._clamp_score(refusal_accuracy),
            latency_ms=max(0, int(latency_ms)),
            cost_usd=float(cost_usd or 0.0),
            token_input_count=max(0, int(token_input_count)),
            token_output_count=max(0, int(token_output_count)),
            judge_used=judge_used,
            judge_provider=judge_provider,
            judge_error=judge_error,
        )

    @staticmethod
    def _mean_or_none(values: list[float | None]) -> float | None:
        normalized = [value for value in values if value is not None]
        if not normalized:
            return None
        return round(float(mean(normalized)), 4)

    def summarize_run(
        self,
        *,
        metrics: list[EvaluationQuestionMetrics],
        total_questions: int,
        success_count: int,
        failure_count: int,
    ) -> dict[str, Any]:
        total_cost_usd = round(sum(item.cost_usd for item in metrics), 6)
        total_input_tokens = sum(item.token_input_count for item in metrics)
        total_output_tokens = sum(item.token_output_count for item in metrics)
        total_latency_ms = sum(item.latency_ms for item in metrics)
        average_latency_ms = round(total_latency_ms / success_count, 2) if success_count > 0 else None
        average_cost_usd = round(total_cost_usd / success_count, 6) if success_count > 0 else None

        summary = {
            "question_total_count": int(total_questions),
            "question_success_count": int(success_count),
            "question_failure_count": int(failure_count),
            "retrieval_hit_rate": self._mean_or_none([item.retrieval_hit_rate for item in metrics]),
            "context_precision": self._mean_or_none([item.context_precision for item in metrics]),
            "context_recall": self._mean_or_none([item.context_recall for item in metrics]),
            "faithfulness_score": self._mean_or_none([item.faithfulness_score for item in metrics]),
            "answer_relevance_score": self._mean_or_none([item.answer_relevance_score for item in metrics]),
            "citation_accuracy_score": self._mean_or_none([item.citation_accuracy_score for item in metrics]),
            "refusal_accuracy": self._mean_or_none([item.refusal_accuracy for item in metrics]),
            "latency_ms_total": total_latency_ms,
            "latency_ms_average": average_latency_ms,
            "cost_usd_total": total_cost_usd,
            "cost_usd_average": average_cost_usd,
            "token_input_count_total": total_input_tokens,
            "token_output_count_total": total_output_tokens,
            "judge_question_count": sum(1 for item in metrics if item.judge_used),
            "judge_error_count": sum(1 for item in metrics if item.judge_error is not None),
        }
        return summary
