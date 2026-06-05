from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import PromptTemplateKey, PromptTemplateVersionState

PromptTemplateKeyLiteral = Literal[
    "answer_generation",
    "summarization",
    "comparison",
    "citation_validation",
    "agent_planning",
]
PromptTemplateStateLiteral = Literal["draft", "review", "published"]


class PromptTemplateVariableDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    description: str | None = Field(default=None, max_length=1000)
    required: bool = True
    default: Any | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class CreatePromptTemplateDraftRequest(BaseModel):
    source_version_number: int | None = Field(default=None, ge=1)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("change_note")
    @classmethod
    def validate_change_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class UpdatePromptTemplateVersionRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=64_000)
    variables: list[PromptTemplateVariableDefinition] | None = Field(
        default=None,
        max_length=100,
    )
    variable_schema: dict[str, Any] | None = Field(default=None)
    preview_context: dict[str, Any] | None = Field(default=None)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("content must not be blank")
        return value

    @field_validator("change_note")
    @classmethod
    def validate_change_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def validate_update_has_changes(self) -> UpdatePromptTemplateVersionRequest:
        if (
            self.content is None
            and self.variables is None
            and self.variable_schema is None
            and self.preview_context is None
            and self.change_note is None
        ):
            raise ValueError("At least one update field is required")
        return self


class PublishPromptTemplateVersionRequest(BaseModel):
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("change_note")
    @classmethod
    def validate_change_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class RollbackPromptTemplateRequest(BaseModel):
    version_number: int = Field(ge=1)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("change_note")
    @classmethod
    def validate_change_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class PromptTemplatePreviewRequest(BaseModel):
    version_number: int | None = Field(default=None, ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=64_000)
    variables: list[PromptTemplateVariableDefinition] | None = Field(
        default=None,
        max_length=100,
    )
    variable_schema: dict[str, Any] | None = Field(default=None)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class PromptTemplateVersionResponse(BaseModel):
    version_id: str
    prompt_template_id: str
    template_key: PromptTemplateKeyLiteral
    version_number: int
    state: PromptTemplateStateLiteral
    is_active: bool
    content: str
    variables: list[dict[str, Any]]
    variable_schema: dict[str, Any]
    preview_context: dict[str, Any]
    change_note: str | None = None
    source_version_number: int | None = None
    created_by_id: str | None = None
    reviewed_by_id: str | None = None
    published_by_id: str | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PromptTemplateResponse(BaseModel):
    prompt_template_id: str
    organization_id: str
    template_key: PromptTemplateKeyLiteral
    name: str
    description: str | None = None
    category: str
    latest_version_number: int
    active_version_number: int | None = None
    active_version_id: str | None = None
    active_state: PromptTemplateStateLiteral | None = None
    active_published_at: datetime | None = None
    eval_run_count: int = 0
    created_by_id: str | None = None
    updated_by_id: str | None = None
    created_at: datetime
    updated_at: datetime


class PromptTemplateListResponse(BaseModel):
    items: list[PromptTemplateResponse]
    total: int
    limit: int
    offset: int


class PromptTemplateVersionListResponse(BaseModel):
    prompt_template_id: str
    template_key: PromptTemplateKeyLiteral
    items: list[PromptTemplateVersionResponse]
    total: int


class PromptTemplateEvalResultResponse(BaseModel):
    evaluation_run_id: str
    evaluation_set_id: str
    run_name: str | None = None
    status: str
    summary: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PromptTemplateEvalResultListResponse(BaseModel):
    prompt_template_id: str
    template_key: PromptTemplateKeyLiteral
    version_number: int
    items: list[PromptTemplateEvalResultResponse]
    total: int
    limit: int
    offset: int


class PromptTemplateDetailResponse(BaseModel):
    template: PromptTemplateResponse
    active_version: PromptTemplateVersionResponse | None = None
    versions: PromptTemplateVersionListResponse
    eval_results: PromptTemplateEvalResultListResponse | None = None


class PromptTemplatePreviewResponse(BaseModel):
    template_key: PromptTemplateKeyLiteral
    version_number: int | None = None
    rendered_prompt: str
    context: dict[str, Any]


def validate_prompt_template_key(value: str) -> str:
    normalized = value.strip()
    if normalized not in {item.value for item in PromptTemplateKey}:
        raise ValueError("Unsupported prompt template key")
    return normalized


def validate_prompt_template_state(value: str) -> str:
    normalized = value.strip()
    if normalized not in {item.value for item in PromptTemplateVersionState}:
        raise ValueError("Unsupported prompt template state")
    return normalized
