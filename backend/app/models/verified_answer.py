"""Verified answers and curated knowledge cards (F255)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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


class VerifiedAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Curated knowledge card — a human-verified answer that can be surfaced above
    generated RAG answers when the query closely matches the stored question."""

    __tablename__ = "verified_answers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending_review', 'approved', 'published', 'archived')",
            name="verified_answers_status_allowed",
        ),
        Index("idx_verified_answers_org_status", "organization_id", "status"),
        Index("idx_verified_answers_org_owner", "organization_id", "owner_id"),
        Index("idx_verified_answers_org_collection", "organization_id", "collection_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # The canonical question this card answers (used for retrieval matching).
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    tags: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Optional scope — card is only surfaced within this collection when set.
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # When False an admin has explicitly waived the citation requirement.
    requires_citations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    approved_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # When promoted from a chat message.
    source_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    citations: Mapped[list[VerifiedAnswerCitation]] = relationship(
        "VerifiedAnswerCitation",
        back_populates="verified_answer",
        cascade="all, delete-orphan",
        order_by="VerifiedAnswerCitation.citation_order",
    )
    versions: Mapped[list[VerifiedAnswerVersion]] = relationship(
        "VerifiedAnswerVersion",
        back_populates="verified_answer",
        cascade="all, delete-orphan",
        order_by="VerifiedAnswerVersion.version_number",
    )
    owner = relationship("User", foreign_keys=[owner_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    created_by = relationship("User", foreign_keys=[created_by_id])


class VerifiedAnswerCitation(UUIDPrimaryKeyMixin, Base):
    """A source document citation attached to a verified answer."""

    __tablename__ = "verified_answer_citations"
    __table_args__ = (
        UniqueConstraint(
            "verified_answer_id",
            "citation_order",
            name="uq_verified_answer_citations_order",
        ),
        Index("idx_va_citations_answer", "verified_answer_id"),
        Index("idx_va_citations_document", "document_id"),
    )

    verified_answer_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("verified_answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    text_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    verified_answer: Mapped[VerifiedAnswer] = relationship(
        "VerifiedAnswer", back_populates="citations"
    )
    document = relationship("Document", foreign_keys=[document_id])


class VerifiedAnswerVersion(UUIDPrimaryKeyMixin, Base):
    """Immutable audit record created on every content edit of a VerifiedAnswer."""

    __tablename__ = "verified_answer_versions"
    __table_args__ = (
        UniqueConstraint(
            "verified_answer_id",
            "version_number",
            name="uq_verified_answer_versions_number",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="verified_answer_versions_number_positive",
        ),
        Index("idx_va_versions_answer", "verified_answer_id"),
    )

    verified_answer_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("verified_answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    change_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    changed_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    verified_answer: Mapped[VerifiedAnswer] = relationship(
        "VerifiedAnswer", back_populates="versions"
    )
    changed_by = relationship("User", foreign_keys=[changed_by_id])
