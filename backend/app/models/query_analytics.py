from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class KnowledgeGap(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "query_knowledge_gaps"
    __table_args__ = (
        CheckConstraint(
            "gap_type IN ('no_answer', 'low_confidence', 'bad_feedback', 'stale_citation', 'missing_source')",
            name="qkg_gap_type_allowed",
        ),
        CheckConstraint(
            "status IN ('open', 'in_review', 'resolved', 'dismissed')",
            name="qkg_status_allowed",
        ),
        CheckConstraint(
            "gap_source IN ('admin', 'low_confidence_analysis', 'feedback_analysis', 'no_answer_analysis')",
            name="qkg_gap_source_allowed",
        ),
        CheckConstraint(
            "converted_to IS NULL OR converted_to IN ('eval_case', 'doc_request', 'review_task')",
            name="qkg_converted_to_allowed",
        ),
        Index("idx_qkg_org_status", "organization_id", "status"),
        Index("idx_qkg_org_created", "organization_id", "created_at"),
        Index("idx_qkg_gap_type", "organization_id", "gap_type"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    gap_type: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    gap_source: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    avg_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    example_query: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    remediation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    linked_document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    linked_eval_question_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    converted_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)

    organization = relationship("Organization", back_populates="knowledge_gaps")
