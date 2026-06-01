"""chunking profile metadata

Revision ID: 20260602_0011
Revises: 20260601_0010
Create Date: 2026-06-02 00:00:00.000000

Adds chunking provenance columns to documents (strategy, version, config snapshot)
and content/structural metadata columns to document_chunks (hash, section path,
language, source offsets).  All new columns are nullable so existing rows are
unaffected — backward compatible with already-indexed documents.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260602_0011"
down_revision: str | None = "20260601_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- documents: chunking provenance ---
    op.add_column(
        "documents",
        sa.Column("chunking_strategy", sa.String(64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("chunking_profile_version", sa.String(32), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("chunking_config_snapshot", sa.JSON(), nullable=True),
    )

    # --- document_chunks: content fingerprint + structural metadata ---
    op.add_column(
        "document_chunks",
        sa.Column("chunk_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("section_path", sa.String(512), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("language", sa.String(32), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_start_offset", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("source_end_offset", sa.Integer(), nullable=True),
    )

    op.create_index("idx_chunks_hash", "document_chunks", ["chunk_hash"])


def downgrade() -> None:
    op.drop_index("idx_chunks_hash", table_name="document_chunks")

    op.drop_column("document_chunks", "source_end_offset")
    op.drop_column("document_chunks", "source_start_offset")
    op.drop_column("document_chunks", "language")
    op.drop_column("document_chunks", "section_path")
    op.drop_column("document_chunks", "chunk_hash")

    op.drop_column("documents", "chunking_config_snapshot")
    op.drop_column("documents", "chunking_profile_version")
    op.drop_column("documents", "chunking_strategy")
