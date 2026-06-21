"""document versioning and change history (F253)

Revision ID: 20260624_0001
Revises: 20260623_0002
Create Date: 2026-06-24

Adds:
  - document_versions — immutable snapshot per version of a document
  - documents.current_version_id — FK to the actively indexed version
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260624_0001"
down_revision: str | None = "20260623_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("change_reason", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("extraction_hash", sa.String(128), nullable=True),
        sa.Column("chunking_profile_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("chunking_profile_snapshot", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column("embedding_vector_dimension", sa.Integer(), nullable=True),
        sa.Column("index_version", sa.String(64), nullable=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "change_reason IN ('initial_upload', 'content_update', 'metadata_update', 'connector_sync', 'reindex', 'tombstone')",
            name="document_versions_change_reason_allowed",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="document_versions_version_number_positive",
        ),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_version",
        ),
    )

    op.create_index(
        "idx_document_versions_document_id",
        "document_versions",
        ["document_id"],
    )
    op.create_index(
        "idx_document_versions_org_id",
        "document_versions",
        ["organization_id"],
    )
    op.create_index(
        "idx_document_versions_document_current",
        "document_versions",
        ["document_id", "is_current"],
    )

    # Add current_version_id FK on documents — deferred to avoid circular at create time.
    op.add_column(
        "documents",
        sa.Column("current_version_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_documents_current_version",
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_index(
        "idx_documents_current_version_id",
        "documents",
        ["current_version_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_documents_current_version_id", table_name="documents")
    op.drop_constraint("fk_documents_current_version", "documents", type_="foreignkey")
    op.drop_column("documents", "current_version_id")

    op.drop_index("idx_document_versions_document_current", table_name="document_versions")
    op.drop_index("idx_document_versions_org_id", table_name="document_versions")
    op.drop_index("idx_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
