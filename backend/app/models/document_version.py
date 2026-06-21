from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable snapshot of a document at a point in its lifecycle.

    A new row is created on: initial upload, content re-upload, connector sync
    with changed content, and explicit reindex with a different chunking profile.
    The is_current flag marks which version is actively indexed in Qdrant.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_version",
        ),
        CheckConstraint(
            "change_reason IN ('initial_upload', 'content_update', 'metadata_update', 'connector_sync', 'reindex', 'tombstone')",
            name="document_versions_change_reason_allowed",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="document_versions_version_number_positive",
        ),
        Index("idx_document_versions_document_id", "document_id"),
        Index("idx_document_versions_org_id", "organization_id"),
        Index("idx_document_versions_document_current", "document_id", "is_current"),
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # What triggered this version record.
    change_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    # SHA-256 of the raw file bytes at this version (matches documents.checksum).
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # SHA-256 of the extracted text after OCR/extraction; set when extraction completes.
    extraction_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Chunking profile snapshot — frozen at the time indexing started.
    chunking_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    chunking_profile_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Embedding provenance — set when indexing completes.
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_vector_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    index_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Document metadata snapshot at the time this version was created.
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # When indexing reached the 'indexed' status for this version.
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # True for the version currently serving Qdrant queries.
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # For connector-synced documents: source system's last-modified timestamp.
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    document = relationship(
        "Document",
        back_populates="versions",
        foreign_keys=[document_id],
    )
    created_by = relationship("User", foreign_keys=[created_by_user_id])
