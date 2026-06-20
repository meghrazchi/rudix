"""Quality gate evaluation service.

Compares evaluation run summary metrics against configured thresholds and
produces a structured verdict + report dict suitable for CI artifact upload.
Supports baseline regression comparison when a baseline_evaluation_run_id is
configured on the gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.domains.quality_gates.schemas.quality_gates import (
    BaselineMetricDelta,
    GateCheckResult,
    QualityGateThresholds,
)
from app.models.enums import QualityGateVerdict

# Maps threshold field → (eval summary key, label, higher_is_better)
_EVAL_THRESHOLD_MAP: list[tuple[str, str, str, bool]] = [
    ("retrieval_hit_rate_min", "retrieval_hit_rate", "Retrieval Hit Rate", True),
    ("citation_accuracy_score_min", "citation_accuracy_score", "Citation Accuracy", True),
    ("faithfulness_score_min", "faithfulness_score", "Faithfulness Score", True),
    ("answer_relevance_score_min", "answer_relevance_score", "Answer Relevance", True),
    ("refusal_accuracy_score_min", "refusal_accuracy_score", "Refusal Accuracy", True),
    ("not_found_rate_max", "not_found_rate", "Not-Found Rate", False),
    ("latency_ms_p95_max", "latency_ms_p95", "Latency p95 (ms)", False),
    ("cost_usd_per_question_max", "cost_usd_per_question", "Cost per Question (USD)", False),
    ("language_adherence_score_min", "language_adherence_score", "Language Adherence", True),
]

# Metrics eligible for regression tracking (higher is better only, 0–1 range)
_REGRESSION_METRICS: list[tuple[str, str]] = [
    ("retrieval_hit_rate", "Retrieval Hit Rate"),
    ("citation_accuracy_score", "Citation Accuracy"),
    ("faithfulness_score", "Faithfulness Score"),
    ("answer_relevance_score", "Answer Relevance"),
    ("refusal_accuracy_score", "Refusal Accuracy"),
    ("language_adherence_score", "Language Adherence"),
]

_SAFETY_THRESHOLD_KEY = "safety_pass_rate_min"


def _metric_float(summary: dict, key: str) -> float | None:
    value = summary.get(key)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def evaluate_gate(
    thresholds: QualityGateThresholds,
    evaluation_summary: dict | None,
    safety_summary: dict | None,
) -> tuple[str, list[GateCheckResult], list[GateCheckResult]]:
    """Return (verdict, passed_checks, failed_checks)."""
    passed: list[GateCheckResult] = []
    failed: list[GateCheckResult] = []

    eval_summary = evaluation_summary or {}
    safety_summary_data = safety_summary or {}

    for threshold_field, summary_key, label, higher_is_better in _EVAL_THRESHOLD_MAP:
        threshold_value = getattr(thresholds, threshold_field)
        if threshold_value is None:
            continue
        actual = _metric_float(eval_summary, summary_key)
        if higher_is_better:
            check_passed = actual is not None and actual >= threshold_value
        else:
            check_passed = actual is not None and actual <= threshold_value
        check = GateCheckResult(
            metric=threshold_field,
            label=label,
            threshold=threshold_value,
            actual=actual,
            passed=check_passed,
            detail=(
                None
                if check_passed
                else (
                    f"actual {actual:.4f} {'<' if higher_is_better else '>'} "
                    f"threshold {threshold_value:.4f}"
                    if actual is not None
                    else "metric not available in evaluation summary"
                )
            ),
        )
        (passed if check_passed else failed).append(check)

    safety_threshold = thresholds.safety_pass_rate_min
    if safety_threshold is not None:
        actual_safety = _metric_float(safety_summary_data, "pass_rate")
        check_passed = actual_safety is not None and actual_safety >= safety_threshold
        check = GateCheckResult(
            metric=_SAFETY_THRESHOLD_KEY,
            label="Safety Pass Rate",
            threshold=safety_threshold,
            actual=actual_safety,
            passed=check_passed,
            detail=(
                None
                if check_passed
                else (
                    f"actual {actual_safety:.4f} < threshold {safety_threshold:.4f}"
                    if actual_safety is not None
                    else "metric not available in safety eval summary"
                )
            ),
        )
        (passed if check_passed else failed).append(check)

    verdict = QualityGateVerdict.passed.value if not failed else QualityGateVerdict.failed.value
    return verdict, passed, failed


def evaluate_regression(
    thresholds: QualityGateThresholds,
    evaluation_summary: dict | None,
    baseline_summary: dict | None,
) -> tuple[list[GateCheckResult], list[BaselineMetricDelta]]:
    """Compare current metrics against a baseline and return regression checks + deltas.

    Returns (regression_failed_checks, all_metric_deltas). Regression checks are
    appended to the main failed_checks list by the caller when the verdict is
    being determined.  Only higher-is-better metrics are regressed (a drop in
    latency/cost is not a regression).
    """
    regression_failed: list[GateCheckResult] = []
    deltas: list[BaselineMetricDelta] = []

    if baseline_summary is None or evaluation_summary is None:
        return regression_failed, deltas

    delta_max = thresholds.regression_delta_max
    if delta_max is None:
        # Still compute deltas for reporting even if no regression threshold
        for summary_key, label in _REGRESSION_METRICS:
            baseline = _metric_float(baseline_summary, summary_key)
            current = _metric_float(evaluation_summary, summary_key)
            if baseline is None and current is None:
                continue
            delta = (current - baseline) if (current is not None and baseline is not None) else None
            deltas.append(
                BaselineMetricDelta(
                    metric=summary_key,
                    label=label,
                    baseline=baseline,
                    current=current,
                    delta=delta,
                    regressed=False,
                )
            )
        return regression_failed, deltas

    for summary_key, label in _REGRESSION_METRICS:
        baseline = _metric_float(baseline_summary, summary_key)
        current = _metric_float(evaluation_summary, summary_key)
        if baseline is None and current is None:
            continue
        delta = (current - baseline) if (current is not None and baseline is not None) else None
        regressed = delta is not None and delta < -delta_max
        deltas.append(
            BaselineMetricDelta(
                metric=summary_key,
                label=label,
                baseline=baseline,
                current=current,
                delta=delta,
                regressed=regressed,
            )
        )
        if regressed:
            assert delta is not None
            regression_failed.append(
                GateCheckResult(
                    metric=f"regression:{summary_key}",
                    label=f"Regression: {label}",
                    threshold=-delta_max,
                    actual=delta,
                    passed=False,
                    detail=(
                        f"metric dropped {abs(delta):.4f} from baseline "
                        f"{baseline:.4f} → {current:.4f} "
                        f"(max allowed drop: {delta_max:.4f})"
                    ),
                )
            )

    return regression_failed, deltas


def build_gate_report(
    *,
    gate_run_id: str,
    quality_gate_id: str,
    quality_gate_name: str,
    verdict: str,
    evaluation_run_id: str | None,
    safety_eval_run_id: str | None,
    thresholds: QualityGateThresholds,
    passed_checks: list[GateCheckResult],
    failed_checks: list[GateCheckResult],
    evaluation_summary: dict | None,
    safety_summary: dict | None,
    baseline_comparison: list[BaselineMetricDelta] | None = None,
    override_reason: str | None = None,
    overridden_by_id: str | None = None,
    overridden_at: datetime | None = None,
) -> dict:
    ci_exit_code = (
        0
        if verdict
        in (
            QualityGateVerdict.passed.value,
            QualityGateVerdict.overridden.value,
        )
        else 1
    )

    report: dict = {
        "gate_run_id": gate_run_id,
        "quality_gate_id": quality_gate_id,
        "quality_gate_name": quality_gate_name,
        "verdict": verdict,
        "generated_at": datetime.now(UTC).isoformat(),
        "evaluation_run_id": evaluation_run_id,
        "safety_eval_run_id": safety_eval_run_id,
        "thresholds_applied": thresholds.model_dump(exclude_none=True),
        "passed_checks": [c.model_dump() for c in passed_checks],
        "failed_checks": [c.model_dump() for c in failed_checks],
        "total_checks": len(passed_checks) + len(failed_checks),
        "pass_count": len(passed_checks),
        "fail_count": len(failed_checks),
        "override_reason": override_reason,
        "overridden_by_id": overridden_by_id,
        "overridden_at": overridden_at.isoformat() if overridden_at else None,
        "evaluation_summary": evaluation_summary,
        "safety_summary": safety_summary,
        "ci_exit_code": ci_exit_code,
    }
    if baseline_comparison is not None:
        report["baseline_comparison"] = [d.model_dump() for d in baseline_comparison]
    return report
