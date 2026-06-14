"""graph_lifecycle_f286: document graph extraction lifecycle columns

Revision ID: 20260615_0004
Revises: 20260615_0003
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "20260615_0004"
down_revision: str | None = "20260615_0003"


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "graph_extraction_status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("graph_extraction_run_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "documents_graph_extraction_status_allowed",
        "documents",
        "graph_extraction_status IN ('pending', 'extracting', 'completed', 'failed', 'skipped')",
    )
    op.alter_column("documents", "graph_extraction_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "documents_graph_extraction_status_allowed",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "graph_extraction_run_id")
    op.drop_column("documents", "graph_extraction_status")
