from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DocumentReviewStatus, DocumentStatus, DocumentTrustStatus

AllowedFileType = Literal["pdf", "txt", "docx"]

ALLOWED_LANGUAGES = frozenset(
    {
        "en",
        "de",
        "fr",
        "es",
        "pt",
        "it",
        "nl",
        "pl",
        "sv",
        "no",
        "da",
        "fi",
        "cs",
        "sk",
        "hu",
        "ro",
        "bg",
        "hr",
        "sl",
        "lt",
        "lv",
        "et",
        "el",
        "tr",
        "ar",
        "fa",
        "zh",
        "ja",
        "ko",
        "ru",
        "uk",
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
    duplicate_detected: bool = False
    duplicate_document_id: str | None = None


class DeleteDocumentResponse(BaseModel):
    document_id: str
    status: Literal["delete_requested", "deleting", "deleted", "retained_by_policy"]
    hold_reason: str | None = None


class BulkDeleteDocumentsRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=100)


class BulkDeleteDocumentResult(BaseModel):
    document_id: str
    status: Literal[
        "delete_requested", "deleting", "deleted", "retained_by_policy", "not_found", "error"
    ]
    hold_reason: str | None = None
    error: str | None = None


class BulkDeleteDocumentsResponse(BaseModel):
    accepted: int
    retained: int
    errors: int
    results: list[BulkDeleteDocumentResult]


class AdminDocumentDeletionItem(BaseModel):
    document_id: str
    filename: str
    file_type: str
    status: DocumentStatus
    organization_id: str
    deletion_requested_at: datetime | None = None
    deletion_hold_reason: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminDocumentDeletionListResponse(BaseModel):
    items: list[AdminDocumentDeletionItem]
    total: int
    limit: int
    offset: int


class RetryDeleteDocumentResponse(BaseModel):
    document_id: str
    status: Literal["delete_requested", "deleting"]
    queue_status: Literal["queued"]


class ReindexDocumentResponse(BaseModel):
    document_id: str
    status: Literal["processing"]
    queue_status: Literal["queued"]


class ReindexDocumentGraphResponse(BaseModel):
    document_id: str
    status: Literal["pending", "extracting", "completed", "failed", "skipped"]
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
    graph_extraction_status: (
        Literal["pending", "extracting", "completed", "failed", "skipped"] | None
    ) = None
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
    graph_extraction_status: (
        Literal["pending", "extracting", "completed", "failed", "skipped"] | None
    ) = None
    page_count: int | None = None
    chunk_count: int
    error_message: str | None = None
    error_details: DocumentErrorDetails | None = None
    source: str | None = None
    source_provider: str | None = None
    language: str | None = None
    retention_class: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[DocumentCollectionSummary] = Field(default_factory=list)
    review_status: DocumentReviewStatus = DocumentReviewStatus.current
    review_owner_id: str | None = None
    review_due_date: date | None = None
    expiry_date: date | None = None
    trust_level: str | None = None
    trust_status: DocumentTrustStatus = DocumentTrustStatus.current
    version_label: str | None = None
    review_date: date | None = None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentListItemResponse]
    total: int
    limit: int
    offset: int
    status: DocumentStatus | None = None
    freshness: DocumentReviewStatus | None = None
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


class DocumentChunkTokenDistributionResponse(BaseModel):
    min_tokens: int
    max_tokens: int
    avg_tokens: float
    total_tokens: int


class DocumentChunkingAdaptiveSignalsResponse(BaseModel):
    file_type: str
    page_count: int
    total_token_count: int
    ocr_applied: bool = False
    heading_density: float | None = None
    avg_chars_per_page: float | None = None
    avg_paragraph_tokens: float | None = None


class DocumentChunkingDiagnosticsResponse(BaseModel):
    strategy: str | None = None
    selected_strategy: str | None = None
    profile_version: str | None = None
    profile_source: str | None = None
    chunk_size_tokens: int | None = None
    chunk_overlap_tokens: int | None = None
    embedding_model: str | None = None
    index_version: str | None = None
    embedding_provider_type: str | None = None
    embedding_vector_dimension: int | None = None
    ocr_applied: bool | None = None
    hierarchical_mode: bool = False
    parent_chunk_count: int | None = None
    child_chunk_count: int | None = None
    reason_codes: list[str] = Field(default_factory=list)
    adaptive_signals: DocumentChunkingAdaptiveSignalsResponse | None = None
    token_distribution: DocumentChunkTokenDistributionResponse | None = None


class DocumentDetailResponse(BaseModel):
    document_id: str
    filename: str
    file_type: AllowedFileType
    status: DocumentStatus
    graph_extraction_status: (
        Literal["pending", "extracting", "completed", "failed", "skipped"] | None
    ) = None
    page_count: int | None = None
    chunk_count: int
    checksum: str | None = None
    error_message: str | None = None
    error_details: DocumentErrorDetails | None = None
    source: str | None = None
    language: str | None = None
    language_confidence: float | None = None
    language_source: str | None = None
    retention_class: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    duplicate_of_document_id: str | None = None
    security_scan_result: dict | None = None
    dlp_scan_result: dict | None = None
    ocr_languages_override: str | None = None
    ocr_quality_snapshot: dict | None = None
    ocr_quality_status: str | None = None
    ocr_avg_confidence: float | None = None
    extraction_snapshot: dict | None = None
    embedding_provider_type: str | None = None
    embedding_vector_dimension: int | None = None
    chunking_diagnostics: DocumentChunkingDiagnosticsResponse | None = None
    lifecycle_timeline: list[DocumentLifecycleTimelineStepResponse] = Field(default_factory=list)
    # Source freshness and trust fields (F297).
    review_status: DocumentReviewStatus = DocumentReviewStatus.current
    review_owner_id: str | None = None
    review_due_date: date | None = None
    expiry_date: date | None = None
    trust_level: str | None = None
    trust_status: DocumentTrustStatus = DocumentTrustStatus.current
    version_label: str | None = None
    superseded_by_document_id: str | None = None
    review_date: date | None = None
    effective_date: date | None = None
    trusted_at: datetime | None = None
    stale_after_days: int | None = None
    created_at: datetime
    updated_at: datetime


class DocumentChunkPreviewResponse(BaseModel):
    chunk_id: str
    page_number: int | None = None
    chunk_index: int
    token_count: int
    embedding_model: str
    index_version: str
    section_path: str | None = None
    language: str | None = None
    chunk_level: int | None = None
    child_count: int | None = None
    source_start_offset: int | None = None
    source_end_offset: int | None = None
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


class DocumentVersionResponse(BaseModel):
    version_id: str
    document_id: str
    version_number: int
    change_reason: str
    content_hash: str | None = None
    extraction_hash: str | None = None
    chunking_profile_snapshot: dict | None = None
    embedding_model: str | None = None
    embedding_vector_dimension: int | None = None
    index_version: str | None = None
    filename: str
    page_count: int | None = None
    chunk_count: int | None = None
    status: str
    indexed_at: datetime | None = None
    is_current: bool
    source_updated_at: datetime | None = None
    created_by_user_id: str | None = None
    created_at: datetime


class DocumentVersionListResponse(BaseModel):
    document_id: str
    items: list[DocumentVersionResponse]
    total: int
