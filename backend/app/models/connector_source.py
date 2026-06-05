from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
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


class SourceDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint(
            "external_item_id",
            "document_id",
            name="uq_source_documents_external_item_document",
        ),
        CheckConstraint("length(content_hash) = 64", name="source_documents_content_hash_length"),
        CheckConstraint("sync_version >= 1", name="source_documents_sync_version_positive"),
        Index("idx_source_documents_org_document", "organization_id", "document_id"),
        Index("idx_source_documents_external_item", "external_item_id"),
        Index("idx_source_documents_collection_id", "collection_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    sync_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    organization = relationship("Organization")
    external_item = relationship("ExternalItem", back_populates="source_documents")
    document = relationship("Document")
    collection = relationship("Collection")
    sync_run = relationship("ConnectorSyncRun", back_populates="source_documents")
    references = relationship(
        "SourceReference",
        back_populates="source_document",
        cascade="all, delete-orphan",
    )


class SourceReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_references"
    __table_args__ = (
        Index("idx_source_references_org_document", "organization_id", "document_id"),
        Index("idx_source_references_external_item", "external_item_id"),
        Index("idx_source_references_chunk_id", "chunk_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_item_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    locator_json: Mapped[dict] = mapped_column("locator", JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    organization = relationship("Organization")
    source_document = relationship("SourceDocument", back_populates="references")
    external_item = relationship("ExternalItem", back_populates="source_references")
    document = relationship("Document")
    chunk = relationship("DocumentChunk")


class ExternalItemTombstone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_item_tombstones"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "connection_id",
            "provider_item_id",
            name="uq_external_item_tombstones_org_connection_provider_item",
        ),
        CheckConstraint(
            "item_type IS NULL OR item_type IN ('issue', 'wiki_page', 'cloud_file', 'folder', 'comment', 'attachment')",
            name="external_item_tombstones_item_type_allowed",
        ),
        Index("idx_external_item_tombstones_org", "organization_id", "tombstoned_at"),
        Index("idx_external_item_tombstones_source", "external_source_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_source_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    sync_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_item_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    item_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    tombstoned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_sync_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    organization = relationship("Organization")
    connection = relationship("ConnectorConnection")
    external_source = relationship("ExternalSource")
    sync_run = relationship("ConnectorSyncRun", back_populates="tombstones")
