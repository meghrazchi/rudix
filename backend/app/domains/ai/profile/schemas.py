"""Pydantic schemas for model profiles (F220)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class TaskType(StrEnum):
    chat = "chat"
    summarization = "summarization"
    comparison = "comparison"
    embeddings = "embeddings"
    evaluations = "evaluations"
    agentic = "agentic"


ALL_TASK_TYPES = list(TaskType)

# Task types that require JSON mode capability
JSON_MODE_REQUIRED_TASKS: frozenset[TaskType] = frozenset(
    {TaskType.evaluations, TaskType.comparison}
)

# Task types that must use an embedding-capable provider
EMBEDDING_TASKS: frozenset[TaskType] = frozenset({TaskType.embeddings})


class ProfileSource(StrEnum):
    env_default = "env_default"
    org_profile = "org_profile"
    request_override = "request_override"


class ProfileValidationIssue(BaseModel):
    field: str
    code: str
    message: str


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UpsertModelProfileRequest(BaseModel):
    profile_name: str = Field(min_length=1, max_length=100)
    provider_type: str = Field(min_length=1, max_length=64)
    base_model: str = Field(min_length=1, max_length=255)
    context_window: int | None = Field(default=None, ge=1, le=2_000_000)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    json_mode: bool = False
    streaming: bool = True
    fallback_provider_key: str | None = Field(default=None, max_length=64)
    is_experimental: bool = False
    cost_metadata: dict = Field(default_factory=dict)
    change_note: str | None = Field(default=None, max_length=1000)

    @field_validator("provider_type")
    @classmethod
    def _normalize_provider_type(cls, v: str) -> str:
        stripped = v.strip().lower()
        if not stripped:
            raise ValueError("provider_type must not be blank")
        return stripped

    @field_validator("base_model")
    @classmethod
    def _normalize_base_model(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("base_model must not be blank")
        return stripped

    @field_validator("fallback_provider_key")
    @classmethod
    def _normalize_fallback(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip().lower()
            if not stripped:
                raise ValueError("fallback_provider_key must not be blank")
            return stripped
        return v

    @model_validator(mode="after")
    def _fallback_differs_from_provider(self) -> UpsertModelProfileRequest:
        if (
            self.fallback_provider_key is not None
            and self.fallback_provider_key == self.provider_type
        ):
            raise ValueError("fallback_provider_key must differ from provider_type")
        return self


class ValidateProfileRequest(BaseModel):
    task_type: TaskType
    provider_type: str = Field(min_length=1, max_length=64)
    base_model: str = Field(min_length=1, max_length=255)
    json_mode: bool = False
    is_experimental: bool = False
    fallback_provider_key: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ModelProfileResponse(BaseModel):
    profile_id: str
    organization_id: str
    profile_name: str
    task_type: TaskType
    provider_type: str
    base_model: str
    context_window: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    json_mode: bool
    streaming: bool
    fallback_provider_key: str | None = None
    is_active: bool
    is_experimental: bool
    cost_metadata: dict
    version: int
    updated_by_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ModelProfileListResponse(BaseModel):
    items: list[ModelProfileResponse]
    total: int


class ResolvedTaskProfile(BaseModel):
    task_type: TaskType
    provider_type: str
    base_model: str
    context_window: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    json_mode: bool
    streaming: bool
    fallback_provider_key: str | None = None
    source: ProfileSource
    version: int


class EffectiveModelPolicyResponse(BaseModel):
    organization_id: str
    profiles: list[ResolvedTaskProfile]
    feature_local_llm_enabled: bool
    feature_local_embeddings_enabled: bool
    feature_fallback_enabled: bool
    feature_request_override_enabled: bool


class ValidateProfileResponse(BaseModel):
    valid: bool
    issues: list[ProfileValidationIssue]
