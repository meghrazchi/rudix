from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CreateSafetyEvalCaseRequest(BaseModel):
    suite_name: str = Field(..., min_length=1, max_length=255)
    violation_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    prompt_text: str = Field(..., min_length=1)
    severity: str = Field(default="high", max_length=32)
    description: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("violation_type")
    @classmethod
    def validate_violation_type(cls, v: str) -> str:
        allowed = {
            "injection",
            "cross_tenant_leakage",
            "private_source_exposure",
            "unsupported_claims",
            "malicious_document",
            "unsafe_transform",
        }
        if v not in allowed:
            raise ValueError(f"violation_type must be one of {sorted(allowed)}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"critical", "high", "medium", "low"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {sorted(allowed)}")
        return v


class SafetyEvalCaseResponse(BaseModel):
    case_id: str
    suite_name: str
    violation_type: str
    name: str
    description: str | None
    prompt_text: str
    severity: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SafetyEvalCaseListResponse(BaseModel):
    items: list[SafetyEvalCaseResponse]
    total: int
    limit: int
    offset: int


class TriggerSafetyEvalRunRequest(BaseModel):
    suite_name: str | None = Field(default=None, max_length=255)
    model_version: str | None = Field(default=None, max_length=128)
    retrieval_settings: dict[str, Any] = Field(default_factory=dict)
    regression_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class SafetyEvalRunResponse(BaseModel):
    run_id: str
    status: str
    suite_name: str | None
    pass_count: int | None
    fail_count: int | None
    total_count: int | None
    pass_rate: float | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SafetyEvalRunListResponse(BaseModel):
    items: list[SafetyEvalRunResponse]
    total: int
    limit: int
    offset: int


class SafetyEvalResultResponse(BaseModel):
    result_id: str
    case_id: str
    case_name: str
    suite_name: str
    violation_type: str
    severity: str
    passed: bool
    violation_detected: bool
    violation_type_detected: str | None
    score: float | None
    latency_ms: int | None
    details: dict[str, Any]
    created_at: datetime


class SafetyEvalRunDetailResponse(BaseModel):
    run_id: str
    status: str
    suite_name: str | None
    config: dict[str, Any]
    pass_count: int | None
    fail_count: int | None
    total_count: int | None
    pass_rate: float | None
    summary: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    results: SafetyEvalResultListResponse


class SafetyEvalResultListResponse(BaseModel):
    items: list[SafetyEvalResultResponse]
    total: int
    limit: int
    offset: int


class TriggerSafetyEvalRunResponse(BaseModel):
    run_id: str
    status: str
    message: str


class SafetyEvalReportResponse(BaseModel):
    run_id: str
    status: str
    generated_at: datetime
    suite_name: str | None
    total_cases: int
    pass_count: int
    fail_count: int
    pass_rate: float
    baseline_pass_rate: float | None
    regression_detected: bool
    regression_threshold: float | None
    by_violation_type: dict[str, dict[str, Any]]
    by_severity: dict[str, dict[str, Any]]
    failed_cases: list[dict[str, Any]]
    summary: dict[str, Any]
