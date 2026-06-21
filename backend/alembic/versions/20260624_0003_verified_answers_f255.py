"""verified answers and curated knowledge cards (F255)

Revision ID: 20260624_0003
Revises: 20260624_0002
Create Date: 2026-06-24

Adds:
  - verified_answers — curated knowledge cards with approval workflow
  - verified_answer_citations — source document references per card
  - verified_answer_versions — immutable edit history per card
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260624_0003"
down_revision: str | None = "20260624_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verified_answers",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("tags", sa.String(1024), nullable=True),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("requires_citations", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("review_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_note", sa.String(2000), nullable=True),
        sa.Column("source_message_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_review', 'approved', 'published', 'archived')",
            name="verified_answers_status_allowed",
        ),
    )
    op.create_index("idx_verified_answers_org_status", "verified_answers", ["organization_id", "status"])
    op.create_index("idx_verified_answers_org_owner", "verified_answers", ["organization_id", "owner_id"])
    op.create_index("idx_verified_answers_org_collection", "verified_answers", ["organization_id", "collection_id"])

    op.create_table(
        "verified_answer_citations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("verified_answer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("text_snippet", sa.Text(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("citation_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["verified_answer_id"], ["verified_answers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "verified_answer_id",
            "citation_order",
            name="uq_verified_answer_citations_order",
        ),
    )
    op.create_index("idx_va_citations_answer", "verified_answer_citations", ["verified_answer_id"])
    op.create_index("idx_va_citations_document", "verified_answer_citations", ["document_id"])

    op.create_table(
        "verified_answer_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("verified_answer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("tags", sa.String(1024), nullable=True),
        sa.Column("change_reason", sa.String(255), nullable=False),
        sa.Column("changed_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["verified_answer_id"], ["verified_answers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "verified_answer_id",
            "version_number",
            name="uq_verified_answer_versions_number",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="verified_answer_versions_number_positive",
        ),
    )
    op.create_index("idx_va_versions_answer", "verified_answer_versions", ["verified_answer_id"])


def downgrade() -> None:
    op.drop_index("idx_va_versions_answer", table_name="verified_answer_versions")
    op.drop_table("verified_answer_versions")

    op.drop_index("idx_va_citations_document", table_name="verified_answer_citations")
    op.drop_index("idx_va_citations_answer", table_name="verified_answer_citations")
    op.drop_table("verified_answer_citations")

    op.drop_index("idx_verified_answers_org_collection", table_name="verified_answers")
    op.drop_index("idx_verified_answers_org_owner", table_name="verified_answers")
    op.drop_index("idx_verified_answers_org_status", table_name="verified_answers")
    op.drop_table("verified_answers")
