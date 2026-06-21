"""Pydantic schemas for taxonomy/metadata management (F256)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MetadataFieldType = Literal["text", "select", "multi_select", "date", "boolean", "number"]


class CreateMetadataFieldRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=256)
    field_type: MetadataFieldType
    allowed_values: list[str] | None = None
    is_required: bool = False
    is_filterable: bool = True
    description: str | None = Field(default=None, max_length=1024)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_allowed_values(self) -> "CreateMetadataFieldRequest":
        if self.field_type in ("select", "multi_select"):
            if not self.allowed_values:
                raise ValueError("allowed_values is required for select/multi_select fields")
            if len(self.allowed_values) > 200:
                raise ValueError("allowed_values must contain at most 200 entries")
        else:
            if self.allowed_values is not None:
                raise ValueError(f"allowed_values is not valid for field_type '{self.field_type}'")
        return self


class UpdateMetadataFieldRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    allowed_values: list[str] | None = None
    is_required: bool | None = None
    is_filterable: bool | None = None
    description: str | None = Field(default=None, max_length=1024)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped


class MetadataFieldResponse(BaseModel):
    field_id: str
    organization_id: str
    name: str
    display_name: str
    field_type: MetadataFieldType
    allowed_values: list[str] | None
    is_required: bool
    is_filterable: bool
    description: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MetadataFieldListResponse(BaseModel):
    items: list[MetadataFieldResponse]
    total: int


# ── Document metadata values ───────────────────────────────────────────────────


class MetadataValueIn(BaseModel):
    """A single field-value pair in a set-metadata request."""

    field_id: str
    value: str | list[str] | bool | float | None

    @field_validator("field_id")
    @classmethod
    def validate_field_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field_id must not be blank")
        return v.strip()


class SetDocumentMetadataRequest(BaseModel):
    """Replaces (upserts) metadata values for a single document."""

    values: list[MetadataValueIn] = Field(min_length=1)


class BulkSetMetadataRequest(BaseModel):
    """Set the same metadata values on multiple documents at once."""

    document_ids: list[str] = Field(min_length=1, max_length=500)
    values: list[MetadataValueIn] = Field(min_length=1)

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, v: list[str]) -> list[str]:
        cleaned = [x.strip() for x in v if x.strip()]
        if not cleaned:
            raise ValueError("document_ids must not be empty")
        return cleaned


class DocumentMetadataValueResponse(BaseModel):
    field_id: str
    field_name: str
    display_name: str
    field_type: MetadataFieldType
    value: str | list[str] | bool | float | None
    updated_at: datetime


class DocumentMetadataResponse(BaseModel):
    document_id: str
    values: list[DocumentMetadataValueResponse]


class BulkSetMetadataResponse(BaseModel):
    updated: int
    skipped: int
    errors: list[str]


# ── Audit log ─────────────────────────────────────────────────────────────────


class MetadataAuditEntryResponse(BaseModel):
    audit_id: str
    document_id: str
    field_id: str
    field_name: str
    changed_by_id: str | None
    old_value: str | None
    new_value: str | None
    action: Literal["set", "delete", "bulk_set"]
    created_at: datetime


class MetadataAuditListResponse(BaseModel):
    items: list[MetadataAuditEntryResponse]
    total: int


# ── Tag suggestion helper ──────────────────────────────────────────────────────


class TagSuggestionResponse(BaseModel):
    """Returns candidate values for a select/multi_select field based on a prefix."""

    field_id: str
    prefix: str
    suggestions: list[str]
