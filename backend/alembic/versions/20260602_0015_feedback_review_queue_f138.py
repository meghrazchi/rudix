"""feedback review queue f138

Revision ID: 20260602_0015
Revises: 20260602_0014
Create Date: 2026-06-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0015"
down_revision: str | None = "20260602_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("new", "triaged", "needs_document", "eval_created", "fixed", "rejected", "duplicate")
_SEVERITIES = ("low", "medium", "high")


def upgrade() -> None:
    op.create_table(
        "feedback_review_items",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("feedback_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="new"),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("reviewer_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("linked_eval_question_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("linked_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _STATUSES)})",
            name=op.f("ck_feedback_review_items_status_allowed"),
        ),
        sa.CheckConstraint(
            f"severity IN ({', '.join(repr(s) for s in _SEVERITIES)})",
            name=op.f("ck_feedback_review_items_severity_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["message_feedback.id"],
            name=op.f("fk_feedback_review_items_feedback_id_message_feedback"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_feedback_review_items_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name=op.f("fk_feedback_review_items_reviewer_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_eval_question_id"],
            ["evaluation_questions.id"],
            name=op.f("fk_feedback_review_items_linked_eval_question_id_evaluation_questions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linked_document_id"],
            ["documents.id"],
            name=op.f("fk_feedback_review_items_linked_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_review_items")),
        sa.UniqueConstraint("feedback_id", name=op.f("uq_feedback_review_items_feedback_id")),
    )
    op.create_index(
        "idx_feedback_review_org_status",
        "feedback_review_items",
        ["organization_id", "status", "created_at"],
    )
    op.create_index(
        "idx_feedback_review_org_created",
        "feedback_review_items",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_feedback_review_org_created", table_name="feedback_review_items")
    op.drop_index("idx_feedback_review_org_status", table_name="feedback_review_items")
    op.drop_table("feedback_review_items")
