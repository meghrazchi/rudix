from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FeedbackReviewStatus, FeedbackSeverity

_REVIEW_STATUSES = tuple(s.value for s in FeedbackReviewStatus)
_SEVERITIES = tuple(s.value for s in FeedbackSeverity)


class FeedbackReviewItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback_review_items"
    __table_args__ = (
        UniqueConstraint("feedback_id", name="uq_feedback_review_feedback"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _REVIEW_STATUSES)})",
            name="feedback_review_items_status_allowed",
        ),
        CheckConstraint(
            f"severity IN ({', '.join(repr(s) for s in _SEVERITIES)})",
            name="feedback_review_items_severity_allowed",
        ),
        Index("idx_feedback_review_org_status", "organization_id", "status", "created_at"),
        Index("idx_feedback_review_org_created", "organization_id", "created_at"),
    )

    feedback_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("message_feedback.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FeedbackReviewStatus.new.value
    )
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default=FeedbackSeverity.medium.value
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewer_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    linked_eval_question_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    linked_document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
