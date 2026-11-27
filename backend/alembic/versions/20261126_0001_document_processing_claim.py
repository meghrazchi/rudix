"""document processing claim columns and stale-processing index (R02-02)

Revision ID: 20261126_0001
Revises: 20260715_0001
Create Date: 2026-11-26 00:00:00.000000

Data-safety notes:
- Additive only. ``processing_task_id`` and ``processing_started_at`` are nullable;
  ``processing_reap_count`` is NOT NULL with ``server_default '0'``. On PostgreSQL 11+
  (including 16) adding a column with a constant default is metadata-only, so no
  table rewrite happens.
- Old code ignores the new columns, so rolling back the application without
  downgrading the schema is safe.
- The partial index only covers rows in ``processing`` and stays small.
- Downgrade drops the index and the three columns; claim state is transient, so no
  durable data is lost.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261126_0001"
down_revision: str | None = "20260715_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("processing_task_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "processing_reap_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "idx_documents_processing_started",
        "documents",
        ["processing_started_at"],
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index("idx_documents_processing_started", table_name="documents")
    op.drop_column("documents", "processing_reap_count")
    op.drop_column("documents", "processing_started_at")
    op.drop_column("documents", "processing_task_id")
