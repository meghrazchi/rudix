from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CollectionAccessPolicy = Literal["org_wide", "admin_only", "selected_roles", "selected_members"]

GranteeType = Literal["role", "member"]

RuleField = Literal[
    "file_type",
    "language",
    "status",
    "ingestion_source",
    "trust_status",
    "uploaded_by_user_id",
    "tags",
]

RuleOperator = Literal["eq", "neq", "in", "not_in", "contains", "not_contains"]

RuleLogic = Literal["and", "or"]


class RuleCondition(BaseModel):
    field: RuleField
    operator: RuleOperator
    value: Any = Field(..., description="String for scalar operators; list for 'in'/'not_in'")


class DynamicRuleSet(BaseModel):
    logic: RuleLogic = "and"
    conditions: list[RuleCondition] = Field(..., min_length=1, max_length=20)


class CollectionListItemResponse(BaseModel):
    collection_id: str
    name: str
    description: str | None
    owner_id: str
    owner_email: str | None
    document_count: int
    indexed_count: int
    access_policy: CollectionAccessPolicy
    is_dynamic: bool
    last_rule_evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CollectionDetailResponse(CollectionListItemResponse):
    created_by_email: str | None
    rule_schema: DynamicRuleSet | None


class CollectionListResponse(BaseModel):
    items: list[CollectionListItemResponse]
    total: int


class CreateCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    access_policy: CollectionAccessPolicy = "org_wide"
    is_dynamic: bool = False
    rule_schema: DynamicRuleSet | None = None


class UpdateCollectionRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    access_policy: CollectionAccessPolicy | None = None


class DeleteCollectionResponse(BaseModel):
    collection_id: str
    archived: bool


class CollectionDocumentItem(BaseModel):
    document_id: str
    filename: str
    file_type: str
    status: str
    updated_at: datetime


class CollectionDocumentsResponse(BaseModel):
    items: list[CollectionDocumentItem]
    total: int


class AddDocumentToCollectionRequest(BaseModel):
    document_id: str


class AddDocumentToCollectionResponse(BaseModel):
    collection_id: str
    document_id: str


class DocumentCollectionsResponse(BaseModel):
    items: list[CollectionListItemResponse]


class SetDocumentCollectionsRequest(BaseModel):
    collection_ids: list[str]


# ── Access policy management ───────────────────────────────────────────────────


class CollectionAccessGrantItem(BaseModel):
    grantee_type: GranteeType
    grantee_value: str  # role name (e.g. "member") or user_id string


class CollectionPolicyResponse(BaseModel):
    collection_id: str
    access_policy: CollectionAccessPolicy
    grants: list[CollectionAccessGrantItem]


class UpdateCollectionPolicyRequest(BaseModel):
    access_policy: CollectionAccessPolicy
    grants: list[CollectionAccessGrantItem] = Field(default_factory=list)


# ── Dynamic rule management ────────────────────────────────────────────────────


class SetCollectionRulesRequest(BaseModel):
    rule_schema: DynamicRuleSet


class CollectionRulesResponse(BaseModel):
    collection_id: str
    is_dynamic: bool
    rule_schema: DynamicRuleSet | None
    last_rule_evaluated_at: datetime | None
    matched_count: int


class PreviewRulesRequest(BaseModel):
    rule_schema: DynamicRuleSet
    limit: int = Field(default=20, ge=1, le=100)


class PreviewRulesDocumentItem(BaseModel):
    document_id: str
    filename: str
    file_type: str
    language: str | None
    status: str
    trust_status: str | None
    tags: str | None
    ingestion_source: str | None


class PreviewRulesResponse(BaseModel):
    total: int
    items: list[PreviewRulesDocumentItem]


class RefreshRulesResponse(BaseModel):
    collection_id: str
    matched_count: int
    last_rule_evaluated_at: datetime | None
