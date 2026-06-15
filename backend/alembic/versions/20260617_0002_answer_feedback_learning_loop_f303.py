"""answer feedback learning loop f303

Revision ID: 20260617_0002
Revises: 20260617_0001
Create Date: 2026-06-17

Adds structured feedback category, diagnostic capture columns, privacy/retention
columns, and eval-conversion tracking to message_feedback.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260617_0002"
down_revision = "20260617_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # F303: structured category
    op.add_column(
        "message_feedback",
        sa.Column("category", sa.String(length=32), nullable=True),
    )

    # F303: diagnostic capture
    op.add_column(
        "message_feedback",
        sa.Column("question_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "message_feedback",
        sa.Column("answer_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "message_feedback",
        sa.Column("citations_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "message_feedback",
        sa.Column(
            "retrieval_diagnostics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "message_feedback",
        sa.Column("model_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "message_feedback",
        sa.Column(
            "rag_profile_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("rag_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # F303: privacy and retention
    op.add_column(
        "message_feedback",
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "message_feedback",
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # F303: eval conversion tracking
    op.add_column(
        "message_feedback",
        sa.Column(
            "converted_to_eval_question_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("evaluation_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Index for category-based filtering
    op.create_index(
        "idx_message_feedback_org_category",
        "message_feedback",
        ["organization_id", "category"],
    )


def downgrade() -> None:
    op.drop_index("idx_message_feedback_org_category", table_name="message_feedback")
    op.drop_column("message_feedback", "converted_to_eval_question_id")
    op.drop_column("message_feedback", "redacted_at")
    op.drop_column("message_feedback", "retain_until")
    op.drop_column("message_feedback", "rag_profile_id")
    op.drop_column("message_feedback", "model_name")
    op.drop_column("message_feedback", "retrieval_diagnostics_json")
    op.drop_column("message_feedback", "citations_json")
    op.drop_column("message_feedback", "answer_text")
    op.drop_column("message_feedback", "question_text")
    op.drop_column("message_feedback", "category")
