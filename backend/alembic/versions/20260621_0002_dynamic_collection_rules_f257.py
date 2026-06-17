"""Dynamic collection rules (F257)

Revision ID: 20260621_0002
Revises: 20260621_0001
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260621_0002"
down_revision = "20260621_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collections",
        sa.Column(
            "is_dynamic",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "collections",
        sa.Column("rule_schema", sa.JSON(), nullable=True),
    )
    op.add_column(
        "collections",
        sa.Column("last_rule_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_collections_is_dynamic",
        "collections",
        ["organization_id", "is_dynamic"],
    )


def downgrade() -> None:
    op.drop_index("idx_collections_is_dynamic", table_name="collections")
    op.drop_column("collections", "last_rule_evaluated_at")
    op.drop_column("collections", "rule_schema")
    op.drop_column("collections", "is_dynamic")
