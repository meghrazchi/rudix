from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QualityGateThresholds(BaseModel):
    """Configurable threshold values for a quality gate.

    All metric fields are optional; only configured ones are enforced.
    P0 thresholds block the deploy unconditionally; P1 thresholds are warnings
    unless the gate's p0_only flag is false (default: all configured thresholds
    are P0).
    """

    retrieval_hit_rate_min: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_accuracy_score_min: float | None = Field(default=None, ge=0.0, le=1.0)
    faithfulness_score_min: float | None = Field(default=None, ge=0.0, le=1.0)
    answer_relevance_score_min: float | None = Field(default=None, ge=0.0, le=1.0)
    not_found_rate_max: float | None = Field(default=None, ge=0.0, le=1.0)
    safety_pass_rate_min: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms_p95_max: float | None = Field(default=None, ge=0.0)
    cost_usd_per_question_max: float | None = Field(default=None, ge=0.0)


class CreateQualityGateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    thresholds: QualityGateThresholds = Field(default_factory=QualityGateThresholds)
    baseline_evaluation_run_id: str | None = None
    baseline_safety_run_id: str | None = None

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


class UpdateQualityGateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None)
    thresholds: QualityGateThresholds | None = None
    baseline_evaluation_run_id: str | None = Field(default=None)
    baseline_safety_run_id: str | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed


class QualityGateResponse(BaseModel):
    quality_gate_id: str
    name: str
    description: str | None = None
    thresholds: dict[str, object]
    baseline_evaluation_run_id: str | None = None
    baseline_safety_run_id: str | None = None
    created_by_id: str | None = None
    created_at: datetime
    updated_at: datetime


class QualityGateListResponse(BaseModel):
    items: list[QualityGateResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Gate run
# ---------------------------------------------------------------------------


class TriggerQualityGateRunRequest(BaseModel):
    evaluation_run_id: str | None = None
    safety_eval_run_id: str | None = None

    @field_validator("evaluation_run_id")
    @classmethod
    def validate_evaluation_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("evaluation_run_id must not be blank")
        return trimmed

    @field_validator("safety_eval_run_id")
    @classmethod
    def validate_safety_eval_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("safety_eval_run_id must not be blank")
        return trimmed


class GateCheckResult(BaseModel):
    metric: str
    label: str
    threshold: float
    actual: float | None
    passed: bool
    detail: str | None = None


class QualityGateRunResponse(BaseModel):
    gate_run_id: str
    quality_gate_id: str
    evaluation_run_id: str | None = None
    safety_eval_run_id: str | None = None
    verdict: Literal["passed", "failed", "overridden"]
    passed_checks: list[GateCheckResult]
    failed_checks: list[GateCheckResult]
    override_reason: str | None = None
    overridden_by_id: str | None = None
    overridden_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class QualityGateRunListResponse(BaseModel):
    items: list[QualityGateRunResponse]
    total: int
    limit: int
    offset: int


class QualityGateOverrideRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < 10:
            raise ValueError("reason must be at least 10 characters")
        return trimmed


class QualityGateReportResponse(BaseModel):
    """Full gate report — returned as CI artifact JSON."""

    gate_run_id: str
    quality_gate_id: str
    quality_gate_name: str
    verdict: str
    generated_at: str
    evaluation_run_id: str | None = None
    safety_eval_run_id: str | None = None
    thresholds_applied: dict[str, object]
    passed_checks: list[GateCheckResult]
    failed_checks: list[GateCheckResult]
    total_checks: int
    pass_count: int
    fail_count: int
    override_reason: str | None = None
    overridden_by_id: str | None = None
    overridden_at: str | None = None
    evaluation_summary: dict[str, object] | None = None
    safety_summary: dict[str, object] | None = None
    ci_exit_code: int
