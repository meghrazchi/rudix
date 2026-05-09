from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class EvaluationSetResponse(BaseModel):
    evaluation_set_id: str
    name: str
    description: str | None = None
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


class EvaluationQuestionResponse(BaseModel):
    evaluation_question_id: str
    evaluation_set_id: str
    question: str
    expected_answer: str | None = None
    expected_document_id: str | None = None
    expected_page_number: int | None = None
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


class TriggerEvaluationRequest(BaseModel):
    document_id: str = Field(min_length=3)
    dataset_name: str = Field(min_length=2, max_length=255)


class TriggerEvaluationResponse(BaseModel):
    evaluation_run_id: str
    status: Literal["queued"] = "queued"


class EvaluationStatusResponse(BaseModel):
    evaluation_run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    score: float | None = None
    updated_at: datetime | None = None
