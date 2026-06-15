from uuid import UUID

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DocumentIngestionSource, DocumentStatus, DocumentTrustStatus, GraphExtractionStatus, OcrQualityStatus


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "file_type IN ('pdf', 'txt', 'docx')",
            name="documents_file_type_allowed",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'indexed', 'failed', 'quarantined', 'blocked', 'delete_requested', 'deleting', 'deleted', 'retained_by_policy', 'pending_scan', 'infected', 'extraction_failed', 'ocr_applied', 'skipped', 'unsupported')",
            name="documents_status_allowed",
        ),
        CheckConstraint(
            "graph_extraction_status IN ('pending', 'extracting', 'completed', 'failed', 'skipped')",
            name="documents_graph_extraction_status_allowed",
        ),
        CheckConstraint(
            "ingestion_source IS NULL OR ingestion_source IN ('upload', 'connector')",
            name="documents_ingestion_source_allowed",
        ),
        CheckConstraint(
            "trust_status IN ('draft', 'current', 'verified', 'stale', 'deprecated', 'superseded', 'expired')",
            name="documents_trust_status_allowed",
        ),
        CheckConstraint(
            "ocr_quality_status IS NULL OR ocr_quality_status IN ('high', 'medium', 'low', 'failed', 'not_required')",
            name="documents_ocr_quality_status_allowed",
        ),
        CheckConstraint(
            "language_source IS NULL OR language_source IN ('upload_provided', 'auto_detected', 'admin_override')",
            name="documents_language_source_allowed",
        ),
        CheckConstraint(
            "page_count IS NULL OR page_count >= 0", name="documents_page_count_non_negative"
        ),
        CheckConstraint(
            "chunk_count IS NULL OR chunk_count >= 0", name="documents_chunk_count_non_negative"
        ),
        Index("idx_documents_org_status", "organization_id", "status"),
        Index("idx_documents_uploaded_by", "uploaded_by_user_id"),
        Index("idx_documents_connector_external_item", "connector_external_item_id"),
        Index("idx_documents_org_trust_status", "organization_id", "trust_status"),
        Index("idx_documents_org_review_date", "organization_id", "review_date"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=DocumentStatus.uploaded.value,
        nullable=False,
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    language_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retention_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # Deletion lifecycle tracking.
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_hold_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # Security scan results — stored without private content.
    duplicate_of_document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    security_scan_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dlp_scan_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Chunking provenance — written once when indexing starts; immutable after that.
    chunking_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunking_profile_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chunking_config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # OCR configuration and quality diagnostics (F232).
    # ocr_languages_override: comma-separated Tesseract codes set by admin to override system default.
    ocr_languages_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ocr_quality_snapshot: quality metrics from the most recent OCR pipeline run.
    ocr_quality_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # extraction_snapshot: structured extraction diagnostics from the F237 PDF extraction pipeline.
    extraction_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Embedding provenance (F219): set when document is indexed; tracks which provider/dimension was used.
    embedding_provider_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    embedding_vector_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_extraction_status: Mapped[str] = mapped_column(
        String(16),
        default=GraphExtractionStatus.pending.value,
        nullable=False,
    )
    graph_extraction_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    # OCR quality scoring (F299): derived from ocr_quality_snapshot after OCR completes.
    # ocr_quality_status: classified tier (high/medium/low/failed/not_required).
    # ocr_avg_confidence: average confidence across completed OCR pages (0.0–1.0).
    ocr_quality_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_avg_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Connector ingestion provenance (F245): links back to the ExternalItem this document came from.
    # NULL for manually uploaded documents.
    ingestion_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    connector_external_item_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Source freshness and trust (F297).
    # trust_status: lifecycle classification used by the retrieval pipeline to boost/exclude docs.
    # version_label: human-readable version string (e.g. "v2.1", "2024-Q3").
    # superseded_by_document_id: points to the newer document when status='superseded'.
    # review_date: next scheduled review; docs past this date may auto-transition to 'stale'.
    # effective_date: when this document became the authoritative version.
    # trusted_at / trusted_by_id: audit trail for 'verified' transitions.
    # stale_after_days: per-document override for the stale threshold.
    trust_status: Mapped[str] = mapped_column(
        String(32),
        default=DocumentTrustStatus.current.value,
        nullable=False,
    )
    version_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    superseded_by_document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    trusted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trusted_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    stale_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    organization = relationship("Organization", back_populates="documents")
    uploader = relationship("User", back_populates="documents")
    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    citations = relationship("Citation", back_populates="document")
    evaluation_questions = relationship("EvaluationQuestion", back_populates="expected_document")
    pipeline_runs = relationship("PipelineRun", back_populates="document")
    collection_memberships = relationship(
        "CollectionDocument", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number"),
        CheckConstraint("page_number >= 1", name="document_pages_page_number_positive"),
        CheckConstraint("char_count >= 0", name="document_pages_char_count_non_negative"),
        Index("idx_document_pages_document_id", "document_id"),
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Per-page OCR confidence (F299): populated when OCR is applied to this page.
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    document = relationship("Document", back_populates="pages")


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", "index_version"),
        UniqueConstraint("qdrant_point_id"),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1", name="document_chunks_page_number_positive"
        ),
        CheckConstraint("chunk_index >= 0", name="document_chunks_chunk_index_non_negative"),
        CheckConstraint("token_count >= 0", name="document_chunks_token_count_non_negative"),
        CheckConstraint(
            "chunk_level IS NULL OR chunk_level >= 0",
            name="document_chunks_chunk_level_non_negative",
        ),
        CheckConstraint(
            "child_count IS NULL OR child_count >= 0",
            name="document_chunks_child_count_non_negative",
        ),
        CheckConstraint(
            "chunk_type IN ('text', 'table', 'image')",
            name="document_chunks_chunk_type_allowed",
        ),
        Index("idx_chunks_document_id", "document_id"),
        Index("idx_chunks_qdrant_point_id", "qdrant_point_id"),
        Index("idx_chunks_parent_chunk_id", "parent_chunk_id"),
        Index("idx_chunks_chunk_level", "chunk_level"),
        Index("idx_chunks_chunk_type", "chunk_type"),
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text(), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    index_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    # Content fingerprint and structural metadata.
    chunk_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Character offsets into the original source text (populated by offset-aware strategies).
    source_start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Hierarchical parent-child chunking (F211).
    # chunk_level=0 means flat or parent; chunk_level=1 means child embedded for retrieval.
    # parent_chunk_id links a child chunk to its parent row in this table.
    # child_count records how many children a parent spawned (informational).
    parent_chunk_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    child_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Table-aware chunking (F298): 'text', 'table', or 'image'.
    chunk_type: Mapped[str] = mapped_column(
        String(16),
        default="text",
        nullable=False,
    )
    # Structured metadata for table chunks (F298). None for text/image chunks.
    table_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # PostgreSQL generated column for full-text search (F293).
    # GENERATED ALWAYS AS — never written by application code.
    text_search_vector = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', COALESCE(text, ''))", persisted=True),
        nullable=True,
    )

    document = relationship("Document", back_populates="chunks")
    citations = relationship("Citation", back_populates="chunk")
