"""Document embedding metadata columns (F219)

Tracks embedding_provider_type and embedding_vector_dimension on documents
to support local embedding provider adapter and vector-dimension safety.

Revision ID: 20260609_0001
Revises: 20260608_0002
Create Date: 2026-06-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_0001"
down_revision: str | None = "20260608_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("embedding_provider_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("embedding_vector_dimension", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "embedding_vector_dimension")
    op.drop_column("documents", "embedding_provider_type")
