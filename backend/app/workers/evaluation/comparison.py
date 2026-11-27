"""Chunking-target summaries, regression flags, comparison and per-dimension winners."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from app.domains.ai.profile.schemas import ResolvedTaskProfile
from app.domains.evaluations.services.evaluation_metrics_service import (
    EvaluationQuestionMetrics,
)
from app.models.document import Document
from app.models.evaluation import EvaluationQuestion
from app.workers.evaluation import facade
from app.workers.evaluation.config import (
    ChunkingComparisonTarget,
    EvaluationRegressionThresholds,
    _normalize_score,
)
from app.workers.evaluation.corpus import ChunkingCorpusStats


def _derive_target_score(summary: dict[str, Any]) -> float | None:
    candidates = [
        summary.get("citation_accuracy_score"),
        summary.get("faithfulness_score"),
        summary.get("retrieval_hit_rate"),
        summary.get("retrieval_mrr"),
        summary.get("context_precision"),
        summary.get("context_recall"),
    ]
    normalized = [_normalize_score(value) for value in candidates]
    usable = [value for value in normalized if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 4)


def _build_regression_flags(
    *,
    baseline_summary: dict[str, Any] | None,
    candidate_summary: dict[str, Any],
    thresholds: EvaluationRegressionThresholds,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []

    def maybe_flag(metric: str, value: float | None, minimum: float | None) -> None:
        if value is None or minimum is None or value >= minimum:
            return
        flags.append(
            {
                "metric": metric,
                "status": "failed",
                "threshold": minimum,
                "value": value,
                "message": f"{metric} dropped below the configured threshold",
            }
        )

    maybe_flag(
        "retrieval_hit_rate",
        _normalize_score(candidate_summary.get("retrieval_hit_rate")),
        thresholds.retrieval_hit_rate_min,
    )
    maybe_flag(
        "citation_accuracy_score",
        _normalize_score(candidate_summary.get("citation_accuracy_score")),
        thresholds.citation_accuracy_score_min,
    )
    maybe_flag(
        "faithfulness_score",
        _normalize_score(candidate_summary.get("faithfulness_score")),
        thresholds.faithfulness_score_min,
    )

    not_found_rate = _normalize_score(candidate_summary.get("not_found_rate"))
    if (
        not_found_rate is not None
        and thresholds.max_not_found_rate is not None
        and not_found_rate > thresholds.max_not_found_rate
    ):
        flags.append(
            {
                "metric": "not_found_rate",
                "status": "failed",
                "threshold": thresholds.max_not_found_rate,
                "value": not_found_rate,
                "message": "not_found_rate exceeded the configured threshold",
            }
        )

    baseline_score = _derive_target_score(baseline_summary or {})
    candidate_score = _derive_target_score(candidate_summary)
    if baseline_score is not None and candidate_score is not None:
        candidate_summary["baseline_score"] = baseline_score
        candidate_summary["latest_score"] = candidate_score
        candidate_summary["score_delta"] = round(candidate_score - baseline_score, 4)

    return flags


def _question_use_case(question: EvaluationQuestion) -> str:
    metadata = question.metadata_json if isinstance(question.metadata_json, dict) else {}
    raw_use_case = metadata.get("use_case")
    if isinstance(raw_use_case, str) and raw_use_case.strip():
        return raw_use_case.strip()
    raw_tags = metadata.get("tags")
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            if isinstance(tag, str) and tag.strip():
                return tag.strip()
    return "unlabeled"


def _summarize_dimension(
    buckets: defaultdict[str, list[tuple[str, float]]],
) -> dict[str, dict[str, Any]]:
    summarized: dict[str, dict[str, Any]] = {}
    for key, values in buckets.items():
        grouped: defaultdict[str, list[float]] = defaultdict(list)
        for label, score in values:
            grouped[label].append(score)
        ranked = sorted(
            (
                (label, round(sum(scores) / len(scores), 4), len(scores))
                for label, scores in grouped.items()
                if scores
            ),
            key=lambda item: (-item[1], item[0]),
        )
        if not ranked:
            continue
        winner = ranked[0]
        summarized[key] = {
            "label": winner[0],
            "score": winner[1],
            "question_count": winner[2],
        }
    return summarized


def _build_best_target_by_dimension(
    *,
    documents_by_id: dict[UUID, Document],
    questions: list[EvaluationQuestion],
    per_target_question_scores: dict[str, dict[str, float | None]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    document_type_scores: defaultdict[str, list[tuple[str, float]]] = defaultdict(list)
    use_case_scores: defaultdict[str, list[tuple[str, float]]] = defaultdict(list)

    for question in questions:
        expected_document = (
            documents_by_id.get(question.expected_document_id)
            if question.expected_document_id is not None
            else None
        )
        document_type = expected_document.file_type if expected_document is not None else "unknown"
        use_case = _question_use_case(question)
        for target_label, question_scores in per_target_question_scores.items():
            score = question_scores.get(str(question.id))
            if score is None:
                continue
            document_type_scores[document_type].append((target_label, score))
            use_case_scores[use_case].append((target_label, score))

    return _summarize_dimension(document_type_scores), _summarize_dimension(use_case_scores)


def _build_target_summary(
    *,
    target: ChunkingComparisonTarget,
    index_version: str,
    corpus_stats: ChunkingCorpusStats,
    metrics: list[EvaluationQuestionMetrics],
    total_questions: int,
    success_count: int,
    failure_count: int,
) -> dict[str, Any]:
    summary = facade()._evaluation_metrics_service.summarize_run(
        metrics=metrics,
        total_questions=total_questions,
        success_count=success_count,
        failure_count=failure_count,
    )
    summary.update(
        {
            "label": target.label,
            "chunking_strategy": target.chunking_strategy,
            "chunking_profile_id": target.chunking_profile_id,
            "profile_version": target.profile_version,
            "profile_source": target.profile_source,
            "index_version": index_version,
            "chunk_count_total": corpus_stats.chunk_count_total,
            "chunk_tokens_average": corpus_stats.chunk_tokens_average,
            "chunk_tokens_variance": corpus_stats.chunk_tokens_variance,
            "chunk_tokens_min": corpus_stats.chunk_tokens_min,
            "chunk_tokens_max": corpus_stats.chunk_tokens_max,
            "document_type_breakdown": corpus_stats.document_type_breakdown,
            "language_breakdown": corpus_stats.language_breakdown,
            "ocr_breakdown": corpus_stats.ocr_breakdown,
        }
    )
    summary["overall_score"] = _derive_target_score(summary)
    return summary


def build_comparison_payload(target_summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Baseline (first target) against the best-scoring candidate, when there are two+."""
    if len(target_summaries) < 2:
        return None
    baseline_summary = target_summaries[0]
    ranked_candidates = sorted(
        target_summaries[1:],
        key=lambda item: (
            item.get("overall_score") is None,
            0.0 if item.get("overall_score") is None else -float(item["overall_score"]),
            str(item.get("label") or ""),
        ),
    )
    latest_summary = ranked_candidates[0]
    baseline_score = _normalize_score(baseline_summary.get("overall_score"))
    latest_score = _normalize_score(latest_summary.get("overall_score"))
    return {
        "baseline_label": baseline_summary.get("label") or "Baseline",
        "baseline_score": baseline_score,
        "latest_label": latest_summary.get("label") or "Candidate",
        "latest_score": latest_score,
        "score_delta": (
            round(latest_score - baseline_score, 4)
            if baseline_score is not None and latest_score is not None
            else None
        ),
    }


def apply_regression_flags(
    target_summaries: list[dict[str, Any]], thresholds: EvaluationRegressionThresholds
) -> tuple[int, bool]:
    """Set ``regression_flags`` on every target; returns (flag count, any failed)."""
    baseline_summary = target_summaries[0] if target_summaries else None
    regression_count = 0
    regression_failed = False
    for index, target_summary in enumerate(target_summaries):
        flags = _build_regression_flags(
            baseline_summary=baseline_summary if index > 0 else None,
            candidate_summary=target_summary,
            thresholds=thresholds,
        )
        target_summary["regression_flags"] = flags
        target_summary["regression_failed"] = len(flags) > 0
        regression_count += len(flags)
        regression_failed = regression_failed or bool(flags)
    return regression_count, regression_failed


def model_profile_summary(profile: ResolvedTaskProfile) -> dict[str, Any]:
    return {
        "provider_type": profile.provider_type,
        "base_model": profile.base_model,
        "source": profile.source.value,
        "task_type": profile.task_type.value,
        "version": profile.version,
        "is_local": profile.provider_type == "local",
    }
