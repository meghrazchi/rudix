from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DocumentStatus

AllowedFileType = Literal["pdf", "txt", "docx"]


class CreateUploadUrlRequest(BaseModel):
    filename: str = Field(min_length=3, max_length=512)
    file_type: AllowedFileType
    file_size_bytes: int = Field(gt=0, le=25 * 1024 * 1024)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        lowered = value.lower()
        if "/" in lowered or "\\" in lowered:
            raise ValueError("filename must not contain path separators")
        return value


class CreateUploadUrlResponse(BaseModel):
    document_id: str
    upload_url: str
    object_key: str
    expires_in_seconds: int = 900


class UploadDocumentResponse(BaseModel):
    document_id: str
    filename: str
    status: Literal["uploaded"]
    queue_status: Literal["queued"]
    checksum: str
    message: str


class DocumentErrorDetails(BaseModel):
    stage: str
    code: str
    category: str
    retryable: bool
    message: str


class DocumentStatusResponse(BaseModel):
    document_id: str
    status: DocumentStatus
    error_message: str | None = None
    error_details: DocumentErrorDetails | None = None
    updated_at: datetime | None = None


DocumentSortBy = Literal["created_at", "updated_at", "filename", "status"]
SortOrder = Literal["asc", "desc"]


class DocumentListItemResponse(BaseModel):
    document_id: str
    filename: str
    file_type: AllowedFileType
    status: DocumentStatus
    page_count: int | None = None
    chunk_count: int
    error_message: str | None = None
    error_details: DocumentErrorDetails | None = None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentListItemResponse]
    total: int
    limit: int
    offset: int
    status: DocumentStatus | None = None
    sort_by: DocumentSortBy
    sort_order: SortOrder


class DocumentDetailResponse(BaseModel):
    document_id: str
    filename: str
    file_type: AllowedFileType
    status: DocumentStatus
    page_count: int | None = None
    chunk_count: int
    checksum: str | None = None
    error_message: str | None = None
    error_details: DocumentErrorDetails | None = None
    created_at: datetime
    updated_at: datetime


class DocumentChunkPreviewResponse(BaseModel):
    chunk_id: str
    page_number: int | None = None
    chunk_index: int
    token_count: int
    embedding_model: str
    index_version: str
    text_preview: str
    text: str | None = None
    created_at: datetime


class DocumentChunksResponse(BaseModel):
    document_id: str
    items: list[DocumentChunkPreviewResponse]
    total: int
    limit: int
    offset: int
    include_full_text: bool = False
