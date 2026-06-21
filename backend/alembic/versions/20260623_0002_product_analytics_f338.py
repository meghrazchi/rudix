"""product analytics policy flag (F338)

Revision ID: 20260623_0002
Revises: 20260623_0001
Create Date: 2026-06-23

Adds:
  - organizations.analytics_enabled — org policy flag that can disable product analytics
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260623_0002"
down_revision: str | None = "20260623_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("analytics_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("organizations", "analytics_enabled")
