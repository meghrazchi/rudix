"""table-aware chunks: chunk_type and table_metadata on document_chunks (F298)

Revision ID: 20260616_0001
Revises: 20260615_0008
Create Date: 2026-06-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260616_0001"
down_revision: str | None = "20260615_0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "chunk_type",
            sa.String(16),
            nullable=False,
            server_default="text",
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column("table_metadata", sa.JSON, nullable=True),
    )
    op.create_check_constraint(
        "document_chunks_chunk_type_allowed",
        "document_chunks",
        "chunk_type IN ('text', 'table', 'image')",
    )
    op.create_index(
        "idx_chunks_chunk_type",
        "document_chunks",
        ["chunk_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_chunks_chunk_type", table_name="document_chunks")
    op.drop_constraint(
        "document_chunks_chunk_type_allowed", "document_chunks", type_="check"
    )
    op.drop_column("document_chunks", "table_metadata")
    op.drop_column("document_chunks", "chunk_type")
