from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CreateAbExperimentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    evaluation_set_id: str
    metrics_config: dict[str, object] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed

    @field_validator("evaluation_set_id")
    @classmethod
    def validate_evaluation_set_id(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("evaluation_set_id must not be blank")
        return trimmed


class UpdateAbExperimentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    metrics_config: dict[str, object] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be blank")
        return trimmed


class CreateAbVariantRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    rag_profile_id: str | None = None
    rag_profile_version: int | None = Field(default=None, ge=1)
    prompt_template_version_id: str | None = None
    model_profile_key: str | None = Field(default=None, max_length=64)
    config_snapshot: dict[str, object] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("label must not be blank")
        return trimmed


class AbVariantResponse(BaseModel):
    variant_id: str
    experiment_id: str
    label: str
    description: str | None = None
    rag_profile_id: str | None = None
    rag_profile_version: int | None = None
    prompt_template_version_id: str | None = None
    model_profile_key: str | None = None
    config_snapshot: dict[str, object]
    approval_status: Literal["pending", "approved", "rejected"]
    approved_by_id: str | None = None
    approval_note: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AbExperimentResponse(BaseModel):
    experiment_id: str
    name: str
    description: str | None = None
    evaluation_set_id: str
    status: Literal["draft", "running", "completed", "failed"]
    metrics_config: dict[str, object]
    created_by_id: str | None = None
    created_at: datetime
    updated_at: datetime
    variants: list[AbVariantResponse] = Field(default_factory=list)


class AbExperimentListResponse(BaseModel):
    items: list[AbExperimentResponse]
    total: int
    limit: int
    offset: int


class StartAbExperimentRunRequest(BaseModel):
    """Trigger a new run of the experiment against all current variants."""

    note: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Variant run / comparison
# ---------------------------------------------------------------------------


class VariantMetricDelta(BaseModel):
    """Per-metric comparison between a variant and a reference (first variant or control)."""

    metric: str
    label: str
    reference_value: float | None
    variant_value: float | None
    delta: float | None
    improved: bool | None


class VariantRunSummary(BaseModel):
    variant_id: str
    variant_label: str
    evaluation_run_id: str | None = None
    status: str
    metrics_summary: dict[str, object]
    deltas_vs_reference: list[VariantMetricDelta] = Field(default_factory=list)
    error_detail: str | None = None


class AbExperimentRunResponse(BaseModel):
    experiment_run_id: str
    experiment_id: str
    status: Literal["draft", "running", "completed", "failed"]
    triggered_by_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    variant_summaries: list[VariantRunSummary] = Field(default_factory=list)
    comparison_report: dict[str, object]


class AbExperimentRunListResponse(BaseModel):
    items: list[AbExperimentRunResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


class ApproveVariantRequest(BaseModel):
    """Promote a variant's RAG profile to the org default after experiment approval."""

    note: str | None = Field(default=None, max_length=2000)
    set_as_default_profile: bool = Field(
        default=False,
        description=(
            "When true, sets the variant's rag_profile as the org default. "
            "Requires the experiment run to be completed."
        ),
    )


class RejectVariantRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
