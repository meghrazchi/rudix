"""Add slug column to collections table.

Revision ID: 20260629_0001
Revises: 20260628_0001
Create Date: 2026-06-29 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0001"
down_revision: str | None = "20260628_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collections",
        sa.Column("slug", sa.String(length=120), nullable=True),
    )
    op.create_unique_constraint(
        "uq_collections_slug",
        "collections",
        ["slug"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_collections_slug", "collections", type_="unique")
    op.drop_column("collections", "slug")
