from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentRuntimeMode(StrEnum):
    auto = "auto"
    answer = "answer"
    summarize = "summarize"
    compare = "compare"


class AgentBudgetConfig(BaseModel):
    max_steps: int = Field(default=12, ge=1, le=200)
    max_runtime_ms: int = Field(default=120_000, ge=500, le=3_600_000)
    max_tool_calls: int = Field(default=30, ge=1, le=500)
    max_total_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    max_total_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1000000"))


class AgentRuntimeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    objective: str = Field(min_length=3, max_length=4000)
    mode: AgentRuntimeMode = AgentRuntimeMode.auto
    question: str | None = Field(default=None, max_length=4000)
    document_query: str | None = Field(default=None, max_length=512)
    document_ids: list[str] = Field(default_factory=list, max_length=200)
    top_k: int | None = Field(default=None, ge=1, le=200)
    rerank: bool | None = None
    approval_ids: dict[str, str] = Field(default_factory=dict, max_length=64)
    budget: AgentBudgetConfig | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("objective must not be blank")
        return normalized

    @field_validator("question", "document_query")
    @classmethod
    def validate_optional_trimmed_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, value: list[str]) -> list[str]:
        normalized_values: list[str] = []
        seen: set[str] = set()
        for raw_value in value:
            normalized = raw_value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_values.append(normalized)
        return normalized_values

    @field_validator("approval_ids")
    @classmethod
    def validate_approval_ids(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_tool_name, raw_approval_id in value.items():
            tool_name = raw_tool_name.strip()
            approval_id = raw_approval_id.strip()
            if not tool_name or not approval_id:
                continue
            normalized[tool_name] = approval_id
        return normalized


class PlannedToolSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_name: str = Field(min_length=3, max_length=120)
    tool_name: str = Field(min_length=3, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = Field(default=None, max_length=800)


class AgentRuntimeError(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    message: str = Field(min_length=1, max_length=400)
    retryable: bool = False
    request_id: str | None = Field(default=None, max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeOutcome(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: dict[str, Any] = Field(default_factory=dict)
    not_found: bool = False
    mode: AgentRuntimeMode


class AgentRuntimeResult(BaseModel):
    run_id: str
    status: str
    steps_executed: int = 0
    tool_calls_executed: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    outcome: AgentRuntimeOutcome | None = None
    error: AgentRuntimeError | None = None
