"""Evaluation run configuration: parsing, comparison targets, regression thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.domains.evaluations.services.evaluation_metrics_service import (
    EvaluationMetricOptions,
)
from app.models.evaluation import EvaluationQuestion
from app.workers.base_task import PermanentTaskError
from app.workers.evaluation import facade


@dataclass(frozen=True)
class ChunkingComparisonTarget:
    label: str
    profile_source: str
    chunking_profile_id: str | None
    chunking_profile_config: dict[str, Any] | None
    chunking_strategy: str | None
    profile_version: str | None


@dataclass(frozen=True)
class EvaluationRegressionThresholds:
    retrieval_hit_rate_min: float | None = None
    citation_accuracy_score_min: float | None = None
    faithfulness_score_min: float | None = None
    max_not_found_rate: float | None = None


@dataclass(frozen=True)
class EvaluationRunConfig:
    run_name: str | None
    top_k: int
    rerank: bool
    model_name: str
    selected_document_ids: list[UUID]
    metric_options: EvaluationMetricOptions
    chunking_profile_id: str | None
    chunking_profile_config: dict[str, Any] | None
    chunking_strategy: str | None
    profile_version: str | None
    comparison_targets: list[ChunkingComparisonTarget]
    regression_thresholds: EvaluationRegressionThresholds
    # Optional: pin a specific OrgModelProfile UUID for this run.
    # When None the org's evaluations task profile is resolved at runtime.
    model_profile_id: str | None = None


def _parse_uuid(value: str) -> UUID:
    return UUID(value)


def _parse_optional_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _normalize_score(value: object) -> float | None:
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0.0, min(1.0, numeric))


def _coerce_score(value: object) -> float | None:
    return _normalize_score(value)


def _normalize_optional_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _parse_regression_thresholds(raw_thresholds: object) -> EvaluationRegressionThresholds:
    if not isinstance(raw_thresholds, dict):
        return EvaluationRegressionThresholds()
    return EvaluationRegressionThresholds(
        retrieval_hit_rate_min=_normalize_score(raw_thresholds.get("retrieval_hit_rate_min")),
        citation_accuracy_score_min=_normalize_score(
            raw_thresholds.get("citation_accuracy_score_min")
        ),
        faithfulness_score_min=_normalize_score(raw_thresholds.get("faithfulness_score_min")),
        max_not_found_rate=_normalize_score(raw_thresholds.get("max_not_found_rate")),
    )


def _parse_comparison_targets(raw_targets: object) -> list[ChunkingComparisonTarget]:
    if not isinstance(raw_targets, list):
        return []
    targets: list[ChunkingComparisonTarget] = []
    for index, raw_target in enumerate(raw_targets, start=1):
        if not isinstance(raw_target, dict):
            continue
        label = _normalize_optional_label(raw_target.get("label")) or f"Target {index}"
        raw_config = raw_target.get("chunking_profile_config")
        config = dict(raw_config) if isinstance(raw_config, dict) else None
        targets.append(
            ChunkingComparisonTarget(
                label=label,
                profile_source=(
                    _normalize_optional_label(raw_target.get("profile_source")) or "system_default"
                ),
                chunking_profile_id=_normalize_optional_label(
                    raw_target.get("chunking_profile_id")
                ),
                chunking_profile_config=config,
                chunking_strategy=_normalize_optional_label(raw_target.get("chunking_strategy")),
                profile_version=_normalize_optional_label(raw_target.get("profile_version")),
            )
        )
    return targets


def _parse_selected_document_ids(raw_selected_document_ids: object) -> list[UUID]:
    if not isinstance(raw_selected_document_ids, list):
        raise PermanentTaskError("Invalid evaluation run config: selected_document_ids")
    selected_document_ids: list[UUID] = []
    seen_document_ids: set[UUID] = set()
    for raw_document_id in raw_selected_document_ids:
        if not isinstance(raw_document_id, str) or not raw_document_id.strip():
            raise PermanentTaskError("Invalid evaluation run config: selected_document_ids")
        try:
            parsed_document_id = UUID(raw_document_id.strip())
        except ValueError as exc:
            raise PermanentTaskError(
                "Invalid evaluation run config: selected_document_ids"
            ) from exc
        if parsed_document_id in seen_document_ids:
            continue
        seen_document_ids.add(parsed_document_id)
        selected_document_ids.append(parsed_document_id)
    return selected_document_ids


def _optional_str(raw_config: dict[str, Any], key: str) -> str | None:
    value = raw_config.get(key)
    if value is not None and not isinstance(value, str):
        raise PermanentTaskError(f"Invalid evaluation run config: {key}")
    return _normalize_optional_label(value)


def _parse_run_config(raw_config: dict[str, Any]) -> EvaluationRunConfig:
    run_name = _normalize_optional_label(raw_config.get("run_name"))
    raw_top_k = raw_config.get("top_k")
    if raw_top_k is None:
        top_k = settings.retrieval_final_top_k
    elif isinstance(raw_top_k, int) and 1 <= raw_top_k <= 200:
        top_k = raw_top_k
    else:
        raise PermanentTaskError("Invalid evaluation run config: top_k")

    raw_rerank = raw_config.get("rerank")
    if raw_rerank is None:
        rerank = True
    elif isinstance(raw_rerank, bool):
        rerank = raw_rerank
    else:
        raise PermanentTaskError("Invalid evaluation run config: rerank")

    raw_model_name = raw_config.get("model_name")
    if raw_model_name is None:
        model_name = settings.openai_llm_model
    elif isinstance(raw_model_name, str) and raw_model_name.strip():
        model_name = raw_model_name.strip()
    else:
        raise PermanentTaskError("Invalid evaluation run config: model_name")

    selected_document_ids = _parse_selected_document_ids(
        raw_config.get("selected_document_ids", [])
    )

    raw_metric_options = raw_config.get("metric_options", {})
    if not isinstance(raw_metric_options, dict):
        raise PermanentTaskError("Invalid evaluation run config: metric_options")

    chunking_profile_id = _optional_str(raw_config, "chunking_profile_id")
    raw_chunking_profile_config = raw_config.get("chunking_profile_config")
    if raw_chunking_profile_config is not None and not isinstance(
        raw_chunking_profile_config, dict
    ):
        raise PermanentTaskError("Invalid evaluation run config: chunking_profile_config")
    chunking_strategy = _optional_str(raw_config, "chunking_strategy")
    profile_version = _optional_str(raw_config, "profile_version")
    model_profile_id = _optional_str(raw_config, "model_profile_id")

    metrics_service = facade()._evaluation_metrics_service
    return EvaluationRunConfig(
        run_name=run_name,
        top_k=top_k,
        rerank=rerank,
        model_name=model_name,
        selected_document_ids=selected_document_ids,
        metric_options=metrics_service.parse_metric_options(dict(raw_metric_options)),
        chunking_profile_id=chunking_profile_id,
        chunking_profile_config=(
            dict(raw_chunking_profile_config)
            if isinstance(raw_chunking_profile_config, dict)
            else None
        ),
        chunking_strategy=chunking_strategy,
        profile_version=profile_version,
        comparison_targets=_parse_comparison_targets(raw_config.get("comparison_targets", [])),
        regression_thresholds=_parse_regression_thresholds(raw_config.get("regression_thresholds")),
        model_profile_id=model_profile_id,
    )


def _resolve_corpus_document_ids(
    *,
    selected_document_ids: list[UUID],
    questions: list[EvaluationQuestion],
) -> list[UUID]:
    if selected_document_ids:
        return selected_document_ids
    derived: list[UUID] = []
    seen: set[UUID] = set()
    for question in questions:
        if question.expected_document_id is None or question.expected_document_id in seen:
            continue
        seen.add(question.expected_document_id)
        derived.append(question.expected_document_id)
    return derived


def resolve_comparison_targets(run_config: EvaluationRunConfig) -> list[ChunkingComparisonTarget]:
    """Explicit targets, else the pinned profile, else the live index."""
    if run_config.comparison_targets:
        return run_config.comparison_targets
    if run_config.chunking_profile_id is not None or run_config.chunking_profile_config is not None:
        return [
            ChunkingComparisonTarget(
                label=run_config.run_name or "Pinned profile",
                profile_source=(
                    "inline_profile"
                    if run_config.chunking_profile_id is None
                    else "organization_profile"
                ),
                chunking_profile_id=run_config.chunking_profile_id,
                chunking_profile_config=run_config.chunking_profile_config,
                chunking_strategy=run_config.chunking_strategy,
                profile_version=run_config.profile_version,
            )
        ]
    return [
        ChunkingComparisonTarget(
            label="Current index",
            profile_source="system_default",
            chunking_profile_id=None,
            chunking_profile_config=None,
            chunking_strategy="live_index",
            profile_version=settings.document_index_version,
        )
    ]
