"""hierarchical parent-child chunking metadata

Revision ID: 20260602_0012
Revises: 20260602_0011
Create Date: 2026-06-02 00:00:00.000000

Adds parent_chunk_id, chunk_level, and child_count to document_chunks so that
hierarchical chunking (small child chunks embedded for retrieval, large parent
chunks kept for context) can be stored alongside flat chunks without schema
migration of existing data.  All new columns are nullable for backward compat.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260602_0012"
down_revision: str | None = "20260602_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("parent_chunk_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("chunk_level", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("child_count", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_document_chunks_parent_chunk_id",
        "document_chunks",
        "document_chunks",
        ["parent_chunk_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_chunks_parent_chunk_id", "document_chunks", ["parent_chunk_id"])
    op.create_index("idx_chunks_chunk_level", "document_chunks", ["chunk_level"])


def downgrade() -> None:
    op.drop_index("idx_chunks_chunk_level", table_name="document_chunks")
    op.drop_index("idx_chunks_parent_chunk_id", table_name="document_chunks")
    op.drop_constraint("fk_document_chunks_parent_chunk_id", "document_chunks", type_="foreignkey")
    op.drop_column("document_chunks", "child_count")
    op.drop_column("document_chunks", "chunk_level")
    op.drop_column("document_chunks", "parent_chunk_id")
