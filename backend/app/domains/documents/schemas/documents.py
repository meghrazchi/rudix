from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DocumentStatus

AllowedFileType = Literal["pdf", "txt", "docx"]

ALLOWED_LANGUAGES = frozenset(
    {
        "en", "de", "fr", "es", "pt", "it", "nl", "pl", "sv", "no",
        "da", "fi", "cs", "sk", "hu", "ro", "bg", "hr", "sl", "lt",
        "lv", "et", "el", "tr", "ar", "fa", "zh", "ja", "ko", "ru", "uk",
    }
)

ALLOWED_RETENTION_CLASSES = frozenset(
    {"standard", "legal_hold", "confidential", "archive", "gdpr_restricted"}
)


def _parse_tags_string(value: str | None) -> list[str]:
    if not value:
        return []
    return [t.strip() for t in value.split(",") if t.strip()]


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


class UploadDocumentMetadata(BaseModel):
    collection_id: str | None = None
    source: str | None = Field(default=None, max_length=512)
    language: str | None = None
    retention_class: str | None = None
    notes: str | None = Field(default=None, max_length=4096)
    tags: list[str] = Field(default_factory=list)

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_LANGUAGES:
            raise ValueError(f"Unsupported language code: {value}")
        return value

    @field_validator("retention_class")
    @classmethod
    def validate_retention_class(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_RETENTION_CLASSES:
            raise ValueError(f"Unsupported retention class: {value}")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        cleaned = [t.strip()[:64] for t in value if t.strip()]
        return cleaned[:20]


class UploadDocumentResponse(BaseModel):
    document_id: str
    filename: str
    status: Literal["uploaded"]
    queue_status: Literal["queued", "deferred"]
    checksum: str
    message: str
    collection_assigned: bool = False


class DeleteDocumentResponse(BaseModel):
    document_id: str
    status: Literal["deleting", "deleted"]


class ReindexDocumentResponse(BaseModel):
    document_id: str
    status: Literal["processing"]
    queue_status: Literal["queued"]


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


class DocumentCollectionSummary(BaseModel):
    collection_id: str
    name: str


class DocumentListItemResponse(BaseModel):
    document_id: str
    filename: str
    file_type: AllowedFileType
    status: DocumentStatus
    page_count: int | None = None
    chunk_count: int
    error_message: str | None = None
    error_details: DocumentErrorDetails | None = None
    source: str | None = None
    language: str | None = None
    retention_class: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[DocumentCollectionSummary] = Field(default_factory=list)
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


class DocumentLifecycleTimelineStepResponse(BaseModel):
    step: str
    label: str
    description: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    document_id: str
    pipeline_run_id: str | None = None
    pipeline_type: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    logs: list[str] = Field(default_factory=list)
    outputs: dict[str, Any] | None = None


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
    source: str | None = None
    language: str | None = None
    retention_class: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    lifecycle_timeline: list[DocumentLifecycleTimelineStepResponse] = Field(default_factory=list)
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
