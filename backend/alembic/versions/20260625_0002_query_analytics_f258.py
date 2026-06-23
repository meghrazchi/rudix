"""query analytics and knowledge-gap dashboard (F258)

Revision ID: 20260625_0002
Revises: 20260625_0001
Create Date: 2026-06-25

Adds:
  - query_knowledge_gaps — persisted gap records identified from query patterns,
    low-confidence answers, bad feedback, and missing sources
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_0002"
down_revision: str | None = "20260625_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "query_knowledge_gaps",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("gap_type", sa.String(32), nullable=False),
        sa.Column("topic_label", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("gap_source", sa.String(32), nullable=False, server_default="admin"),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("avg_confidence", sa.Float(), nullable=True),
        sa.Column("example_query", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("remediation_json", sa.JSON(), nullable=True),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("linked_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("linked_eval_question_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("converted_to", sa.String(32), nullable=True),
        sa.Column(
            "converted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["linked_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["linked_eval_question_id"],
            ["evaluation_questions.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "gap_type IN ('no_answer', 'low_confidence', 'bad_feedback', 'stale_citation', 'missing_source')",
            name="qkg_gap_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_review', 'resolved', 'dismissed')",
            name="qkg_status_allowed",
        ),
        sa.CheckConstraint(
            "gap_source IN ('admin', 'low_confidence_analysis', 'feedback_analysis', 'no_answer_analysis')",
            name="qkg_gap_source_allowed",
        ),
        sa.CheckConstraint(
            "converted_to IS NULL OR converted_to IN ('eval_case', 'doc_request', 'review_task')",
            name="qkg_converted_to_allowed",
        ),
    )
    op.create_index("idx_qkg_org_status", "query_knowledge_gaps", ["organization_id", "status"])
    op.create_index(
        "idx_qkg_org_created", "query_knowledge_gaps", ["organization_id", "created_at"]
    )
    op.create_index("idx_qkg_gap_type", "query_knowledge_gaps", ["organization_id", "gap_type"])


def downgrade() -> None:
    op.drop_index("idx_qkg_gap_type", table_name="query_knowledge_gaps")
    op.drop_index("idx_qkg_org_created", table_name="query_knowledge_gaps")
    op.drop_index("idx_qkg_org_status", table_name="query_knowledge_gaps")
    op.drop_table("query_knowledge_gaps")
