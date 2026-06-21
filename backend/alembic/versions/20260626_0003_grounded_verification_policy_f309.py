"""Grounded verification policy controls (F309).

Revision ID: 20260626_0003
Revises: 20260626_0002
Create Date: 2026-06-26

Adds:
  - grounded_verification_mode and grounded_verification_threshold to org
    AI response policies
  - matching nullable override fields for collection-level policy overrides
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_0003"
down_revision: str | None = "20260626_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "org_ai_response_policies",
        sa.Column(
            "grounded_verification_mode",
            sa.String(32),
            nullable=False,
            server_default="off",
        ),
    )
    op.add_column(
        "org_ai_response_policies",
        sa.Column("grounded_verification_threshold", sa.Float(), nullable=True),
    )
    op.create_check_constraint(
        "org_ai_policy_grounded_verification_mode_allowed",
        "org_ai_response_policies",
        "grounded_verification_mode IN ('off', 'standard', 'strict')",
    )

    op.add_column(
        "collection_ai_response_policy_overrides",
        sa.Column("grounded_verification_mode", sa.String(32), nullable=True),
    )
    op.add_column(
        "collection_ai_response_policy_overrides",
        sa.Column("grounded_verification_threshold", sa.Float(), nullable=True),
    )
    op.create_check_constraint(
        "col_ai_policy_grounded_verification_mode_allowed",
        "collection_ai_response_policy_overrides",
        "grounded_verification_mode IS NULL OR grounded_verification_mode IN ('off', 'standard', 'strict')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "col_ai_policy_grounded_verification_mode_allowed",
        "collection_ai_response_policy_overrides",
        type_="check",
    )
    op.drop_column("collection_ai_response_policy_overrides", "grounded_verification_threshold")
    op.drop_column("collection_ai_response_policy_overrides", "grounded_verification_mode")

    op.drop_constraint(
        "org_ai_policy_grounded_verification_mode_allowed",
        "org_ai_response_policies",
        type_="check",
    )
    op.drop_column("org_ai_response_policies", "grounded_verification_threshold")
    op.drop_column("org_ai_response_policies", "grounded_verification_mode")
