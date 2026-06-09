import csv
import io
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domains.admin.schemas.chunking_profiles import ChunkingProfileConfigInput


class CreateEvaluationSetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("description must not be blank")
        return trimmed


class UpdateEvaluationSetRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None)
    scope: dict[str, object] | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed


class EvaluationSetResponse(BaseModel):
    evaluation_set_id: str
    name: str
    description: str | None = None
    status: str = "draft"
    version: int = 1
    owner_id: str | None = None
    scope: dict[str, object] = Field(default_factory=dict)
    question_count: int = 0
    created_at: datetime
    updated_at: datetime


class EvaluationSetListResponse(BaseModel):
    items: list[EvaluationSetResponse]
    total: int
    limit: int
    offset: int


class CreateEvaluationQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    expected_answer: str | None = Field(default=None, max_length=8000)
    expected_document_id: str | None = None
    expected_page_number: int | None = Field(default=None, ge=1)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("question must not be blank")
        return trimmed

    @field_validator("expected_answer")
    @classmethod
    def validate_expected_answer(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("expected_answer must not be blank")
        return trimmed

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        normalized_tags: list[str] = []
        for tag in value:
            trimmed = tag.strip()
            if not trimmed:
                raise ValueError("tags must not contain blank values")
            normalized_tags.append(trimmed)
        return normalized_tags


class UpdateEvaluationQuestionRequest(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=8000)
    expected_answer: str | None = Field(default=None)
    expected_document_id: str | None = Field(default=None)
    expected_page_number: int | None = Field(default=None, ge=1)
    difficulty: Literal["easy", "medium", "hard"] | None = Field(default=None)
    tags: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, object] | None = Field(default=None)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("question must not be blank")
        return trimmed

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        normalized: list[str] = []
        for tag in value:
            trimmed = tag.strip()
            if not trimmed:
                raise ValueError("tags must not contain blank values")
            normalized.append(trimmed)
        return normalized


class EvaluationQuestionResponse(BaseModel):
    evaluation_question_id: str
    evaluation_set_id: str
    question: str
    expected_answer: str | None = None
    expected_document_id: str | None = None
    expected_page_number: int | None = None
    difficulty: str | None = None
    owner_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class EvaluationQuestionListResponse(BaseModel):
    evaluation_set_id: str
    items: list[EvaluationQuestionResponse]
    total: int
    limit: int
    offset: int


class ImportCaseRow(BaseModel):
    question: str
    expected_answer: str | None = None
    expected_page_number: int | None = Field(default=None, ge=1)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("question must not be blank")
        return trimmed


class ImportCasesRequest(BaseModel):
    format: Literal["csv", "json"] = "json"
    data: str = Field(min_length=1, max_length=500_000)
    skip_duplicates: bool = True

    @model_validator(mode="after")
    def validate_data_parses(self) -> "ImportCasesRequest":
        if self.format == "json":
            try:
                parsed = json.loads(self.data)
            except json.JSONDecodeError as exc:
                raise ValueError(f"data is not valid JSON: {exc}") from exc
            if not isinstance(parsed, list):
                raise ValueError("JSON data must be an array of case objects")
        elif self.format == "csv":
            reader = csv.DictReader(io.StringIO(self.data))
            if reader.fieldnames is None or "question" not in reader.fieldnames:
                raise ValueError("CSV data must include a 'question' column")
        return self


class ImportCasesResponse(BaseModel):
    imported: int
    skipped_duplicates: int
    validation_errors: list[str]


class ConvertFeedbackToCasesRequest(BaseModel):
    evaluation_set_id: str = Field(min_length=3, max_length=64)
    feedback_ids: list[str] = Field(min_length=1, max_length=100)
    default_difficulty: Literal["easy", "medium", "hard"] | None = None

    @field_validator("evaluation_set_id")
    @classmethod
    def validate_set_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("evaluation_set_id must not be blank")
        return trimmed

    @field_validator("feedback_ids")
    @classmethod
    def validate_feedback_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for fid in value:
            trimmed = fid.strip()
            if not trimmed:
                raise ValueError("feedback_ids must not contain blank values")
            normalized.append(trimmed)
        return normalized


class ConvertFeedbackToCasesResponse(BaseModel):
    created: int
    skipped: int
    evaluation_set_id: str


class DatasetValidationIssue(BaseModel):
    evaluation_question_id: str
    question_preview: str
    issue_type: Literal[
        "missing_scope",
        "deleted_source",
        "inaccessible_document",
        "no_expected_answer",
        "duplicate",
    ]
    detail: str


class ValidateDatasetResponse(BaseModel):
    evaluation_set_id: str
    is_valid: bool
    issue_count: int
    issues: list[DatasetValidationIssue]


class EvaluationDatasetVersionResponse(BaseModel):
    version_id: str
    evaluation_set_id: str
    version_number: int
    question_count: int
    published_by_id: str | None = None
    published_at: datetime | None = None
    created_at: datetime


class EvaluationDatasetVersionListResponse(BaseModel):
    evaluation_set_id: str
    items: list[EvaluationDatasetVersionResponse]
    total: int


class PublishDatasetResponse(BaseModel):
    evaluation_set_id: str
    version_number: int
    question_count: int
    status: Literal["published"] = "published"


class DuplicateDatasetResponse(BaseModel):
    evaluation_set_id: str
    name: str
    question_count: int
    status: Literal["draft"] = "draft"
    created_at: datetime


class EvaluationChunkingComparisonTargetInput(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    chunking_profile_id: str | None = None
    chunking_profile_config: ChunkingProfileConfigInput | None = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("label must not be blank")
        return trimmed

    @model_validator(mode="after")
    def validate_target(self) -> "EvaluationChunkingComparisonTargetInput":
        if self.chunking_profile_id is not None and self.chunking_profile_config is not None:
            raise ValueError(
                "Provide either chunking_profile_id or chunking_profile_config, not both"
            )
        if self.chunking_profile_id is None and self.chunking_profile_config is None:
            raise ValueError(
                "comparison target requires chunking_profile_id or chunking_profile_config"
            )
        return self


class EvaluationRegressionThresholds(BaseModel):
    retrieval_hit_rate_min: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_accuracy_score_min: float | None = Field(default=None, ge=0.0, le=1.0)
    faithfulness_score_min: float | None = Field(default=None, ge=0.0, le=1.0)
    max_not_found_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class EvaluationRunConfig(BaseModel):
    run_name: str | None = Field(default=None, min_length=1, max_length=120)
    top_k: int | None = Field(default=None, ge=1, le=200)
    rerank: bool = True
    model_name: str | None = Field(default=None, min_length=3, max_length=128)
    selected_document_ids: list[str] = Field(default_factory=list, max_length=50)
    metric_options: dict[str, bool | int | float | str] = Field(default_factory=dict)
    chunking_profile_id: str | None = None
    chunking_profile_config: ChunkingProfileConfigInput | None = None
    comparison_targets: list[EvaluationChunkingComparisonTargetInput] = Field(
        default_factory=list,
        max_length=6,
    )
    regression_thresholds: EvaluationRegressionThresholds | None = None

    @field_validator("run_name")
    @classmethod
    def validate_run_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("run_name must not be blank")
        return trimmed

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("model_name must not be blank")
        return trimmed

    @field_validator("selected_document_ids")
    @classmethod
    def validate_selected_document_ids(cls, value: list[str]) -> list[str]:
        normalized_ids: list[str] = []
        for document_id in value:
            trimmed = document_id.strip()
            if not trimmed:
                raise ValueError("selected_document_ids must not contain blank values")
            normalized_ids.append(trimmed)
        return normalized_ids

    @model_validator(mode="after")
    def validate_chunking_configuration(self) -> "EvaluationRunConfig":
        has_single_target = (
            self.chunking_profile_id is not None or self.chunking_profile_config is not None
        )
        if self.chunking_profile_id is not None and self.chunking_profile_config is not None:
            raise ValueError(
                "Provide either chunking_profile_id or chunking_profile_config, not both"
            )
        if has_single_target and self.comparison_targets:
            raise ValueError(
                "Provide either a single chunking profile override or comparison_targets, not both"
            )
        if self.comparison_targets and len(self.comparison_targets) < 2:
            raise ValueError("comparison_targets must include at least two profiles")
        return self


class RunEvaluationRequest(BaseModel):
    evaluation_set_id: str = Field(min_length=3, max_length=64)
    config: EvaluationRunConfig = Field(default_factory=EvaluationRunConfig)

    @field_validator("evaluation_set_id")
    @classmethod
    def validate_evaluation_set_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("evaluation_set_id must not be blank")
        return trimmed


class RunEvaluationResponse(BaseModel):
    evaluation_run_id: str
    status: Literal["queued"] = "queued"


class EvaluationStatusResponse(BaseModel):
    evaluation_run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    score: float | None = None
    updated_at: datetime | None = None


class EvaluationRunResultResponse(BaseModel):
    evaluation_result_id: str
    evaluation_question_id: str
    question: str
    status: str
    generated_answer: str | None = None
    retrieval_score: float | None = None
    faithfulness_score: float | None = None
    citation_accuracy_score: float | None = None
    answer_relevance_score: float | None = None
    latency_ms: int | None = None
    metrics: dict[str, object] = Field(default_factory=dict)
    failure_reason: str | None = None
    failure_type: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class EvaluationRunResultListResponse(BaseModel):
    items: list[EvaluationRunResultResponse]
    total: int
    limit: int
    offset: int


class EvaluationRunDetailResponse(BaseModel):
    evaluation_run_id: str
    evaluation_set_id: str
    status: Literal["queued", "running", "completed", "failed"]
    config: dict[str, object] = Field(default_factory=dict)
    summary: dict[str, object] | None = None
    failure_reason: str | None = None
    failure_type: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    results: EvaluationRunResultListResponse
    model_profile_key: str | None = None
    provider_type: str | None = None
    provider_profile: str | None = None


class EvaluationRunSummaryResponse(BaseModel):
    evaluation_run_id: str
    evaluation_set_id: str
    run_name: str | None = None
    status: str
    summary: dict[str, object] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_profile_key: str | None = None
    provider_type: str | None = None
    provider_profile: str | None = None


class EvaluationRunListResponse(BaseModel):
    items: list[EvaluationRunSummaryResponse]
    total: int
    limit: int
    offset: int


class MetricDelta(BaseModel):
    metric: str
    label: str
    run_a_value: float | None = None
    run_b_value: float | None = None
    delta: float | None = None
    is_regression: bool = False
    is_improvement: bool = False


class CaseComparisonRow(BaseModel):
    evaluation_question_id: str
    question: str
    difficulty: str | None = None
    tags: list[str] = Field(default_factory=list)
    run_a: EvaluationRunResultResponse | None = None
    run_b: EvaluationRunResultResponse | None = None
    regression: bool = False
    improvement: bool = False


class RunComparisonResponse(BaseModel):
    run_a: EvaluationRunSummaryResponse
    run_b: EvaluationRunSummaryResponse
    metric_deltas: list[MetricDelta]
    regression_count: int
    improvement_count: int
    cases: list[CaseComparisonRow]
    total_cases: int
    filters_applied: dict[str, object] = Field(default_factory=dict)


EvaluationRunConfig.model_rebuild()
RunEvaluationRequest.model_rebuild()


# ---------------------------------------------------------------------------
# F226 — Local model evaluation, benchmark suites, and model profile comparison
# ---------------------------------------------------------------------------


class LocalModelMetrics(BaseModel):
    """Local-provider-specific quality indicators stored in config metrics_summary."""

    invalid_json_rate: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Fraction of responses that failed JSON parsing (evaluations task)",
    )
    timeout_rate: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Fraction of inference calls that exceeded the configured timeout",
    )
    fallback_frequency: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Fraction of calls that fell back to the fallback provider",
    )
    estimated_compute_latency_ms: float | None = Field(
        default=None, ge=0.0,
        description="Median end-to-end latency in ms (estimated from result latency_ms values)",
    )
    tokens_per_second: float | None = Field(
        default=None, ge=0.0,
        description="Estimated token throughput when reported by the local provider",
    )


class BenchmarkSuiteResponse(BaseModel):
    suite_id: str
    name: str
    description: str
    quality_dimension: str
    case_count: int


class BenchmarkSuiteListResponse(BaseModel):
    items: list[BenchmarkSuiteResponse]
    total: int


class TriggerBenchmarkRunRequest(BaseModel):
    suite_id: str = Field(min_length=1, max_length=64)
    provider_profile: Literal["cloud_baseline", "local_profile", "fallback_profile"] = (
        "local_profile"
    )
    evaluation_set_id: str | None = Field(
        default=None,
        description=(
            "Use an existing evaluation set. If omitted a temporary set is created "
            "from the suite's seed cases."
        ),
    )
    top_k: int = Field(default=5, ge=1, le=50)
    rerank: bool = True

    @field_validator("suite_id")
    @classmethod
    def validate_suite_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("suite_id must not be blank")
        return trimmed


class TriggerBenchmarkRunResponse(BaseModel):
    evaluation_run_id: str
    suite_id: str
    provider_profile: str
    status: Literal["queued"] = "queued"


class ProviderProfileSummary(BaseModel):
    """Aggregated quality summary for one provider profile label."""

    provider_profile: str
    provider_type: str | None = None
    run_count: int
    latest_run_id: str | None = None
    retrieval_hit_rate: float | None = None
    citation_accuracy_score: float | None = None
    faithfulness_score: float | None = None
    answer_relevance_score: float | None = None
    not_found_rate: float | None = None
    latency_ms_average: float | None = None
    cost_usd_total: float | None = None
    local_model_metrics: LocalModelMetrics | None = None


class ReleaseGateRecommendation(BaseModel):
    """Pass/fail recommendation for promoting a local model profile."""

    provider_profile: str
    is_ready: bool
    failing_checks: list[str]
    passing_checks: list[str]
    recommendation: str


_DEFAULT_GATE_THRESHOLDS: dict[str, float] = {
    "retrieval_hit_rate_min": 0.70,
    "citation_accuracy_score_min": 0.75,
    "faithfulness_score_min": 0.70,
    "answer_relevance_score_min": 0.70,
    "not_found_rate_max": 0.20,
    "invalid_json_rate_max": 0.05,
    "timeout_rate_max": 0.10,
    "fallback_frequency_max": 0.15,
}


def _build_release_gate_recommendation(
    summary: "ProviderProfileSummary",
    thresholds: dict[str, float] | None = None,
) -> ReleaseGateRecommendation:
    t = dict(_DEFAULT_GATE_THRESHOLDS)
    if thresholds:
        t.update(thresholds)

    local = summary.local_model_metrics or LocalModelMetrics()
    checks: list[tuple[str, bool]] = [
        (
            f"retrieval_hit_rate ≥ {t['retrieval_hit_rate_min']:.0%}",
            summary.retrieval_hit_rate is not None
            and summary.retrieval_hit_rate >= t["retrieval_hit_rate_min"],
        ),
        (
            f"citation_accuracy ≥ {t['citation_accuracy_score_min']:.0%}",
            summary.citation_accuracy_score is not None
            and summary.citation_accuracy_score >= t["citation_accuracy_score_min"],
        ),
        (
            f"faithfulness ≥ {t['faithfulness_score_min']:.0%}",
            summary.faithfulness_score is not None
            and summary.faithfulness_score >= t["faithfulness_score_min"],
        ),
        (
            f"answer_relevance ≥ {t['answer_relevance_score_min']:.0%}",
            summary.answer_relevance_score is not None
            and summary.answer_relevance_score >= t["answer_relevance_score_min"],
        ),
        (
            f"not_found_rate ≤ {t['not_found_rate_max']:.0%}",
            summary.not_found_rate is None
            or summary.not_found_rate <= t["not_found_rate_max"],
        ),
        (
            f"invalid_json_rate ≤ {t['invalid_json_rate_max']:.0%}",
            local.invalid_json_rate is None
            or local.invalid_json_rate <= t["invalid_json_rate_max"],
        ),
        (
            f"timeout_rate ≤ {t['timeout_rate_max']:.0%}",
            local.timeout_rate is None
            or local.timeout_rate <= t["timeout_rate_max"],
        ),
        (
            f"fallback_frequency ≤ {t['fallback_frequency_max']:.0%}",
            local.fallback_frequency is None
            or local.fallback_frequency <= t["fallback_frequency_max"],
        ),
    ]

    passing = [label for label, passed in checks if passed]
    failing = [label for label, passed in checks if not passed]
    is_ready = len(failing) == 0

    if is_ready:
        recommendation = (
            f"Profile '{summary.provider_profile}' meets all release-gate thresholds "
            "and is safe to promote to default."
        )
    else:
        recommendation = (
            f"Profile '{summary.provider_profile}' fails {len(failing)} check(s): "
            + ", ".join(failing)
            + ". Resolve these before promoting to default."
        )

    return ReleaseGateRecommendation(
        provider_profile=summary.provider_profile,
        is_ready=is_ready,
        failing_checks=failing,
        passing_checks=passing,
        recommendation=recommendation,
    )


class ModelProfileComparisonReport(BaseModel):
    """Cloud-baseline vs local-profile vs fallback-profile quality comparison."""

    organization_id: str
    evaluation_set_id: str | None = None
    profiles: list[ProviderProfileSummary]
    release_gate_recommendations: list[ReleaseGateRecommendation]
    default_thresholds: dict[str, float] = Field(
        default_factory=lambda: dict(_DEFAULT_GATE_THRESHOLDS)
    )
    generated_at: datetime
