"""Vector index generations for zero-downtime reindex (schema from R06-01 part 2; chain A).

``VectorIndexGeneration`` is global (one Qdrant collection serves every organisation, and
payload filters scope it), so it has no tenant column. ``VectorIndexGenerationDocument``
records, per organisation, which documents a generation already holds.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import UUIDPrimaryKeyMixin

GENERATION_STATES = ("building", "verifying", "active", "retired", "failed", "dropped")


class VectorIndexGeneration(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "vector_index_generations"
    __table_args__ = (
        UniqueConstraint("collection_name", name="uq_vector_index_generations_collection"),
        UniqueConstraint(
            "alias_name", "generation", name="uq_vector_index_generations_alias_generation"
        ),
        CheckConstraint(
            "state IN ('building', 'verifying', 'active', 'retired', 'failed', 'dropped')",
            name="state_allowed",
        ),
    )

    alias_name: Mapped[str] = mapped_column(String(128), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    vector_size: Mapped[int] = mapped_column(Integer, nullable=False)
    distance: Mapped[str] = mapped_column(String(16), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="building", server_default="building"
    )
    build_cursor: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expected_points: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    indexed_points: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    documents_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    documents_done: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retire_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class VectorIndexGenerationDocument(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "vector_index_generation_documents"
    __table_args__ = (
        UniqueConstraint(
            "generation_id",
            "document_id",
            name="uq_vector_index_generation_documents_generation_document",
        ),
        Index("idx_vector_index_generation_documents_org", "organization_id", "generation_id"),
    )

    generation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("vector_index_generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
