"""guided first-run onboarding config (F327)

Revision ID: 20260623_0001
Revises: 20260622_0002
Create Date: 2026-06-23

Adds:
  - organizations.sample_docs_enabled — flag enabling sample dataset loading for demo workspaces
  - organizations.onboarding_reset_at — timestamp allowing admins to force-reset onboarding for all org users
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260623_0001"
down_revision: str | None = "20260622_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("sample_docs_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "organizations",
        sa.Column("onboarding_reset_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "onboarding_reset_at")
    op.drop_column("organizations", "sample_docs_enabled")
