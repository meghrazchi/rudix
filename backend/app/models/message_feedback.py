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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FeedbackRating


class MessageFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_feedback_message_user"),
        CheckConstraint(
            f"rating IN ('{FeedbackRating.up}', '{FeedbackRating.down}')",
            name="message_feedback_rating_allowed",
        ),
        Index("idx_message_feedback_message", "message_id"),
        Index("idx_message_feedback_org_user", "organization_id", "user_id"),
        Index("idx_message_feedback_org_category", "organization_id", "category"),
    )

    message_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # F303 — structured category replaces/augments free-form reason
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # F303 — diagnostic context captured at submission time
    question_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    citations_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retrieval_diagnostics_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rag_profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rag_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )

    # F303 — privacy and retention
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # F303 — tracks if this feedback was converted to an eval case
    converted_to_eval_question_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_questions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # F316 — trust-panel accuracy feedback fields
    trust_metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    selected_citation_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
