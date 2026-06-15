"""A/B experiment comparison and reporting service.

Handles metric delta computation across variants, comparison report generation,
and evaluation run metric extraction.  Does not run the evaluation engine itself
— that happens in the existing EvaluationRepository / evaluation pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domains.ab_testing.schemas.ab_testing import (
    VariantMetricDelta,
    VariantRunSummary,
)
from app.models.ab_experiment import AbExperimentRun, AbExperimentVariantRun

# Ordered list of metrics used in comparison reports (higher-is-better)
_QUALITY_METRICS: list[tuple[str, str]] = [
    ("retrieval_hit_rate", "Retrieval Hit Rate"),
    ("faithfulness_score", "Faithfulness Score"),
    ("citation_accuracy_score", "Citation Accuracy"),
    ("answer_relevance_score", "Answer Relevance"),
    ("refusal_accuracy_score", "Refusal Accuracy"),
    ("language_adherence_score", "Language Adherence"),
]

# Lower-is-better operational metrics
_OPERATIONAL_METRICS: list[tuple[str, str]] = [
    ("latency_ms_p95", "Latency p95 (ms)"),
    ("cost_usd_per_question", "Cost per Question (USD)"),
    ("not_found_rate", "Not-Found Rate"),
]


def _float(summary: dict, key: str) -> float | None:
    v = summary.get(key)
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def compute_variant_deltas(
    reference_summary: dict,
    variant_summary: dict,
) -> list[VariantMetricDelta]:
    """Compute per-metric delta for one variant relative to a reference variant."""
    deltas: list[VariantMetricDelta] = []

    for key, label in _QUALITY_METRICS:
        ref = _float(reference_summary, key)
        val = _float(variant_summary, key)
        delta = (val - ref) if (ref is not None and val is not None) else None
        improved = (delta > 0) if delta is not None else None
        deltas.append(
            VariantMetricDelta(
                metric=key,
                label=label,
                reference_value=ref,
                variant_value=val,
                delta=delta,
                improved=improved,
            )
        )

    for key, label in _OPERATIONAL_METRICS:
        ref = _float(reference_summary, key)
        val = _float(variant_summary, key)
        delta = (val - ref) if (ref is not None and val is not None) else None
        # For lower-is-better metrics, improved means delta < 0
        improved = (delta < 0) if delta is not None else None
        deltas.append(
            VariantMetricDelta(
                metric=key,
                label=label,
                reference_value=ref,
                variant_value=val,
                delta=delta,
                improved=improved,
            )
        )

    return deltas


def build_variant_summaries(
    variant_runs: list[AbExperimentVariantRun],
    variant_labels: dict[str, str],
) -> list[VariantRunSummary]:
    """Build per-variant summaries with deltas vs the first (reference) variant."""
    if not variant_runs:
        return []

    completed = [vr for vr in variant_runs if vr.status == "completed"]
    reference_summary: dict = {}
    if completed:
        reference_summary = dict(completed[0].metrics_summary or {})

    summaries: list[VariantRunSummary] = []
    for idx, vr in enumerate(variant_runs):
        ms = dict(vr.metrics_summary or {})
        deltas = (
            compute_variant_deltas(reference_summary, ms)
            if idx > 0 and vr.status == "completed"
            else []
        )
        summaries.append(
            VariantRunSummary(
                variant_id=str(vr.variant_id),
                variant_label=variant_labels.get(str(vr.variant_id), "Unknown"),
                evaluation_run_id=str(vr.evaluation_run_id) if vr.evaluation_run_id else None,
                status=vr.status,
                metrics_summary=ms,
                deltas_vs_reference=deltas,
                error_detail=vr.error_detail,
            )
        )
    return summaries


def build_comparison_report(
    *,
    experiment_run_id: str,
    experiment_id: str,
    experiment_name: str,
    evaluation_set_id: str,
    variant_summaries: list[VariantRunSummary],
    note: str | None = None,
) -> dict:
    completed = [s for s in variant_summaries if s.status == "completed"]

    # Determine best variant per quality metric
    winner_by_metric: dict[str, str] = {}
    for key, label in _QUALITY_METRICS:
        best_label: str | None = None
        best_val: float | None = None
        for s in completed:
            v = _float(dict(s.metrics_summary), key)
            if v is not None and (best_val is None or v > best_val):
                best_val = v
                best_label = s.variant_label
        if best_label:
            winner_by_metric[label] = best_label

    return {
        "experiment_run_id": experiment_run_id,
        "experiment_id": experiment_id,
        "experiment_name": experiment_name,
        "evaluation_set_id": evaluation_set_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
        "variant_count": len(variant_summaries),
        "completed_variant_count": len(completed),
        "winner_by_metric": winner_by_metric,
        "variant_summaries": [s.model_dump() for s in variant_summaries],
    }


def extract_metrics_from_eval_config(eval_run_config: dict) -> dict:
    """Extract the metrics_summary from an EvaluationRun.config dict."""
    summary = eval_run_config.get("metrics_summary")
    if isinstance(summary, dict):
        return dict(summary)
    return {}
