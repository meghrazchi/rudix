"""document lifecycle F212: chunk_count and profile_source metadata

Revision ID: 20260602_0013
Revises: 20260602_0012
Create Date: 2026-06-02 00:00:00.000000

Adds chunk_count to documents so callers can read the current indexed chunk
count without parsing the JSON snapshot.  The column is nullable so existing
rows are unaffected — backward compatible with already-indexed documents.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260602_0013"
down_revision: str | None = "20260602_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("chunk_count", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "documents_chunk_count_non_negative",
        "documents",
        "chunk_count IS NULL OR chunk_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("documents_chunk_count_non_negative", "documents", type_="check")
    op.drop_column("documents", "chunk_count")
