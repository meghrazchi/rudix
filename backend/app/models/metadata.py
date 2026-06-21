"""Custom metadata fields and document metadata values (F256)."""

from __future__ import annotations

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
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class MetadataField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Org-level taxonomy definition: declares a metadata field and its constraints."""

    __tablename__ = "metadata_fields"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_metadata_fields_org_name"),
        CheckConstraint(
            "field_type IN ('text', 'select', 'multi_select', 'date', 'boolean', 'number')",
            name="metadata_fields_type_allowed",
        ),
        Index("idx_metadata_fields_org", "organization_id", "is_active"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    field_type: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed_values: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_filterable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    document_values: Mapped[list[DocumentMetadata]] = relationship(
        "DocumentMetadata",
        back_populates="field",
        cascade="all, delete-orphan",
    )


class DocumentMetadata(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single metadata field value attached to a document."""

    __tablename__ = "document_metadata"
    __table_args__ = (
        UniqueConstraint("document_id", "field_id", name="uq_document_metadata_doc_field"),
        Index("idx_document_metadata_doc", "document_id"),
        Index("idx_document_metadata_field", "field_id"),
        Index("idx_document_metadata_org", "organization_id"),
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("metadata_fields.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    field: Mapped[MetadataField] = relationship("MetadataField", back_populates="document_values")


class MetadataAuditLog(UUIDPrimaryKeyMixin, Base):
    """Immutable record of every metadata value change on a document."""

    __tablename__ = "metadata_audit_log"
    __table_args__ = (
        CheckConstraint(
            "action IN ('set', 'delete', 'bulk_set')",
            name="metadata_audit_action_allowed",
        ),
        Index("idx_metadata_audit_doc", "document_id"),
        Index("idx_metadata_audit_field", "field_id"),
        Index("idx_metadata_audit_org_created", "organization_id", "created_at"),
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("metadata_fields.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    changed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="set")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
