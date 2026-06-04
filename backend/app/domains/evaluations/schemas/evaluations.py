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


EvaluationRunConfig.model_rebuild()
RunEvaluationRequest.model_rebuild()
