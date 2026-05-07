from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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
from app.models.enums import DocumentStatus


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "file_type IN ('pdf', 'txt', 'docx')",
            name="documents_file_type_allowed",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'indexed', 'failed', 'deleting', 'deleted')",
            name="documents_status_allowed",
        ),
        CheckConstraint("page_count IS NULL OR page_count >= 0", name="documents_page_count_non_negative"),
        Index("idx_documents_org_status", "organization_id", "status"),
        Index("idx_documents_uploaded_by", "uploaded_by_user_id"),
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
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)

    organization = relationship("Organization", back_populates="documents")
    uploader = relationship("User", back_populates="documents")
    pages = relationship("DocumentPage", back_populates="document", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    citations = relationship("Citation", back_populates="document")
    evaluation_questions = relationship("EvaluationQuestion", back_populates="expected_document")


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

    document = relationship("Document", back_populates="pages")


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", "index_version"),
        UniqueConstraint("qdrant_point_id"),
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="document_chunks_page_number_positive"),
        CheckConstraint("chunk_index >= 0", name="document_chunks_chunk_index_non_negative"),
        CheckConstraint("token_count >= 0", name="document_chunks_token_count_non_negative"),
        Index("idx_chunks_document_id", "document_id"),
        Index("idx_chunks_qdrant_point_id", "qdrant_point_id"),
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

    document = relationship("Document", back_populates="chunks")
    citations = relationship("Citation", back_populates="chunk")
