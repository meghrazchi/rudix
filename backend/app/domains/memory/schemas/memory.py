"""Pydantic schemas for org workflow memory and user preferences (F343)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Patterns that may indicate sensitive data — rejected in query templates.
_REDACT_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"(?:password|secret|token|api[_\-]?key)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
]


def _check_no_sensitive(value: str, field_name: str) -> str:
    for pattern in _REDACT_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                f"{field_name} must not contain sensitive data "
                "(emails, passwords, tokens, or bearer strings)"
            )
    return value


# ---------------------------------------------------------------------------
# Workflow step schema
# ---------------------------------------------------------------------------


class WorkflowStepIn(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    query_template: str | None = Field(default=None, max_length=1000)
    scope: Literal["all", "collection", "docs", "none"] = "all"
    collection_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("label")
    @classmethod
    def strip_label(cls, v: str) -> str:
        return v.strip()

    @field_validator("query_template")
    @classmethod
    def validate_query_template(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        return _check_no_sensitive(v, "query_template")

    @field_validator("collection_ids")
    @classmethod
    def validate_collection_ids(cls, v: list[str]) -> list[str]:
        import uuid

        validated: list[str] = []
        for cid in v:
            try:
                validated.append(str(uuid.UUID(cid)))
            except ValueError as exc:
                raise ValueError(f"Invalid collection_id: {cid!r}") from exc
        return validated


class WorkflowStepResponse(BaseModel):
    label: str
    query_template: str | None
    scope: str
    collection_ids: list[str]


# ---------------------------------------------------------------------------
# Org workflow schemas
# ---------------------------------------------------------------------------


class CreateWorkflowRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    workflow_type: Literal[
        "audit_evidence_pack",
        "policy_comparison",
        "contract_review",
        "onboarding_faq",
        "custom",
    ] = "custom"
    steps: list[WorkflowStepIn] = Field(default_factory=list, max_length=20)
    role_scope: list[str] | None = None
    collection_scope_ids: list[str] | None = None
    verified_knowledge_card_id: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return _check_no_sensitive(v.strip(), "name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _check_no_sensitive(v.strip(), "description")

    @field_validator("role_scope")
    @classmethod
    def validate_role_scope(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        allowed = {"owner", "admin", "member", "viewer", "reviewer", "developer"}
        for r in v:
            if r not in allowed:
                raise ValueError(f"Unknown role: {r!r}")
        return list(dict.fromkeys(v))  # deduplicate preserving order

    @field_validator("collection_scope_ids")
    @classmethod
    def validate_collection_scope_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        import uuid

        validated: list[str] = []
        for cid in v:
            try:
                validated.append(str(uuid.UUID(cid)))
            except ValueError as exc:
                raise ValueError(f"Invalid collection_id: {cid!r}") from exc
        return validated


class UpdateWorkflowRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    workflow_type: (
        Literal[
            "audit_evidence_pack",
            "policy_comparison",
            "contract_review",
            "onboarding_faq",
            "custom",
        ]
        | None
    ) = None
    steps: list[WorkflowStepIn] | None = None
    role_scope: list[str] | None = None
    collection_scope_ids: list[str] | None = None
    verified_knowledge_card_id: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _check_no_sensitive(v.strip(), "name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _check_no_sensitive(v.strip(), "description")


class WorkflowResponse(BaseModel):
    workflow_id: str
    organization_id: str
    created_by_id: str | None
    name: str
    description: str | None
    workflow_type: str
    status: str
    steps: list[WorkflowStepResponse]
    role_scope: list[str] | None
    collection_scope_ids: list[str] | None
    verified_knowledge_card_id: str | None
    use_count: int
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    items: list[WorkflowResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# User memory preference schemas
# ---------------------------------------------------------------------------


class UpsertMemoryPreferenceRequest(BaseModel):
    preferred_scope: Literal["all", "collection", "docs", "none"] | None = None
    preferred_collection_ids: list[str] | None = None
    rag_profile_id: str | None = None
    answer_language: str | None = Field(default=None, max_length=8)
    extra_defaults: dict[str, Any] | None = None

    @field_validator("preferred_collection_ids")
    @classmethod
    def validate_collection_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        import uuid

        validated: list[str] = []
        for cid in v:
            try:
                validated.append(str(uuid.UUID(cid)))
            except ValueError as exc:
                raise ValueError(f"Invalid collection_id: {cid!r}") from exc
        return validated

    @field_validator("extra_defaults")
    @classmethod
    def validate_extra_defaults(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError("extra_defaults must not exceed 20 keys")
        for key, val in v.items():
            if not isinstance(key, str):
                raise ValueError("extra_defaults keys must be strings")
            if not isinstance(val, (str, int, float, bool, type(None))):
                raise ValueError("extra_defaults values must be scalar types")
            if isinstance(val, str) and len(val) > 512:
                raise ValueError(f"extra_defaults[{key!r}] must be ≤ 512 characters")
            if isinstance(key, str):
                _check_no_sensitive(str(val), f"extra_defaults[{key!r}]")
        return v


class MemoryPreferenceResponse(BaseModel):
    preference_id: str
    organization_id: str
    user_id: str
    preferred_scope: str | None
    preferred_collection_ids: list[str] | None
    rag_profile_id: str | None
    answer_language: str | None
    extra_defaults: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
