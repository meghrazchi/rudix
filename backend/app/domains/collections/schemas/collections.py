from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CollectionAccessPolicy = Literal["org_wide", "restricted"]


class CollectionListItemResponse(BaseModel):
    collection_id: str
    name: str
    description: str | None
    owner_id: str
    owner_email: str | None
    document_count: int
    indexed_count: int
    access_policy: CollectionAccessPolicy
    created_at: datetime
    updated_at: datetime


class CollectionDetailResponse(CollectionListItemResponse):
    created_by_email: str | None


class CollectionListResponse(BaseModel):
    items: list[CollectionListItemResponse]
    total: int


class CreateCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    access_policy: CollectionAccessPolicy = "org_wide"


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
