"""document upload metadata fields

Revision ID: 20260601_0007
Revises: 20260531_0006
Create Date: 2026-06-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260601_0007"
down_revision: str | None = "20260531_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source", sa.String(512), nullable=True))
    op.add_column("documents", sa.Column("language", sa.String(32), nullable=True))
    op.add_column("documents", sa.Column("retention_class", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("tags", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "tags")
    op.drop_column("documents", "notes")
    op.drop_column("documents", "retention_class")
    op.drop_column("documents", "language")
    op.drop_column("documents", "source")
