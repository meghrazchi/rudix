"""Pydantic schemas for the AI response policy engine (F268)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

CitationMode = Literal["required", "recommended", "disabled"]
NoAnswerBehavior = Literal["refuse", "warn", "allow"]
StaleSourceBehavior = Literal["warn", "refuse", "ignore"]
DisclaimerPosition = Literal["prepend", "append"]
PolicyOutcome = Literal["allowed", "blocked", "warned"]
PolicySource = Literal["org", "collection", "none"]


# ---------------------------------------------------------------------------
# Org policy CRUD schemas
# ---------------------------------------------------------------------------


class CreateAiResponsePolicyRequest(BaseModel):
    policy_name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    citation_mode: CitationMode = "recommended"
    min_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    no_answer_behavior: NoAnswerBehavior = "warn"
    stale_source_behavior: StaleSourceBehavior = "warn"
    blocked_topics: list[str] = Field(default_factory=list)
    allowed_topics: list[str] | None = None
    min_sources_required: int | None = Field(default=None, ge=0)
    disclaimer_text: str | None = Field(default=None, max_length=2048)
    disclaimer_position: DisclaimerPosition = "prepend"
    refusal_message: str | None = Field(default=None, max_length=1024)


class UpdateAiResponsePolicyRequest(BaseModel):
    policy_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    citation_mode: CitationMode | None = None
    min_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    no_answer_behavior: NoAnswerBehavior | None = None
    stale_source_behavior: StaleSourceBehavior | None = None
    blocked_topics: list[str] | None = None
    allowed_topics: list[str] | None = None
    min_sources_required: int | None = Field(default=None, ge=0)
    disclaimer_text: str | None = None
    disclaimer_position: DisclaimerPosition | None = None
    refusal_message: str | None = None
    is_active: bool | None = None


class AiResponsePolicyResponse(BaseModel):
    policy_id: str
    organization_id: str
    policy_name: str
    description: str | None
    is_active: bool
    citation_mode: CitationMode
    min_confidence_threshold: float | None
    no_answer_behavior: NoAnswerBehavior
    stale_source_behavior: StaleSourceBehavior
    blocked_topics: list[str]
    allowed_topics: list[str] | None
    min_sources_required: int | None
    disclaimer_text: str | None
    disclaimer_position: DisclaimerPosition
    refusal_message: str | None
    created_by_id: str | None
    updated_by_id: str | None
    created_at: datetime
    updated_at: datetime


class AiResponsePolicyListResponse(BaseModel):
    items: list[AiResponsePolicyResponse]
    total: int


# ---------------------------------------------------------------------------
# Collection override schemas
# ---------------------------------------------------------------------------


class UpsertCollectionPolicyOverrideRequest(BaseModel):
    citation_mode: CitationMode | None = None
    min_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    no_answer_behavior: NoAnswerBehavior | None = None
    stale_source_behavior: StaleSourceBehavior | None = None
    blocked_topics: list[str] | None = None
    allowed_topics: list[str] | None = None
    min_sources_required: int | None = Field(default=None, ge=0)
    disclaimer_text: str | None = None
    refusal_message: str | None = None


class CollectionPolicyOverrideResponse(BaseModel):
    override_id: str
    org_policy_id: str
    collection_id: str
    citation_mode: CitationMode | None
    min_confidence_threshold: float | None
    no_answer_behavior: NoAnswerBehavior | None
    stale_source_behavior: StaleSourceBehavior | None
    blocked_topics: list[str] | None
    allowed_topics: list[str] | None
    min_sources_required: int | None
    disclaimer_text: str | None
    refusal_message: str | None
    updated_by_id: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Policy preview / test schema
# ---------------------------------------------------------------------------


class PolicyPreviewRequest(BaseModel):
    """Simulate policy evaluation for a hypothetical chat scenario."""

    question: str = Field(min_length=1, max_length=1024)
    confidence_score: float = Field(ge=0.0, le=1.0, default=1.0)
    citation_count: int = Field(ge=0, default=0)
    stale_source_count: int = Field(ge=0, default=0)
    collection_id: str | None = None
    policy_id: str | None = None  # Test a specific (possibly inactive) policy


class PolicyPreviewResponse(BaseModel):
    outcome: PolicyOutcome
    policy_source: PolicySource
    policy_id: str | None
    violated_rules: list[str]
    warning_flags: list[str]
    refusal_message: str | None
    disclaimer_text: str | None
    disclaimer_position: DisclaimerPosition


# ---------------------------------------------------------------------------
# Policy evaluation logs
# ---------------------------------------------------------------------------


class PolicyEvaluationLogResponse(BaseModel):
    log_id: str
    organization_id: str
    user_id: str | None
    org_policy_id: str | None
    collection_id: str | None
    chat_session_id: str | None
    chat_message_id: str | None
    outcome: PolicyOutcome
    policy_source: PolicySource
    violated_rules: list[str]
    warning_flags: list[str]
    question_preview: str | None
    confidence_score: float | None
    citation_count: int | None
    stale_source_count: int | None
    is_preview_run: bool
    created_at: datetime


class PolicyEvaluationLogListResponse(BaseModel):
    items: list[PolicyEvaluationLogResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Internal evaluation result — used by the policy engine service
# ---------------------------------------------------------------------------


class PolicyEvaluationResult(BaseModel):
    """Result of evaluating an AI response against the active policy."""

    blocked: bool = False
    warned: bool = False
    violated_rules: list[str] = Field(default_factory=list)
    warning_flags: list[str] = Field(default_factory=list)
    refusal_message: str | None = None
    disclaimer_text: str | None = None
    disclaimer_position: DisclaimerPosition = "prepend"
    policy_id: str | None = None
    policy_source: PolicySource = "none"

    @property
    def outcome(self) -> PolicyOutcome:
        if self.blocked:
            return "blocked"
        if self.warned:
            return "warned"
        return "allowed"
