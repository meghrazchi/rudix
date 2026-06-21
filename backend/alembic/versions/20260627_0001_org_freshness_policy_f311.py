"""Org-level freshness policy thresholds (F311).

Revision ID: 20260627_0001
Revises: 20260626_0003
Create Date: 2026-06-27

Adds:
  - org_freshness_policies: per-org admin-configurable freshness warning
    thresholds (warn_stale_after_days, warn_unreviewed_after_days,
    auto_exclude_deprecated, auto_exclude_expired, label).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0001"
down_revision: str | None = "20260626_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_freshness_policies",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("warn_stale_after_days", sa.Integer(), nullable=True),
        sa.Column("warn_unreviewed_after_days", sa.Integer(), nullable=True),
        sa.Column("auto_exclude_deprecated", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("auto_exclude_expired", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_org_freshness_policy_org"),
        sa.CheckConstraint(
            "warn_stale_after_days IS NULL OR warn_stale_after_days >= 1",
            name="ck_ofp_stale_days_min",
        ),
        sa.CheckConstraint(
            "warn_stale_after_days IS NULL OR warn_stale_after_days <= 3650",
            name="ck_ofp_stale_days_max",
        ),
        sa.CheckConstraint(
            "warn_unreviewed_after_days IS NULL OR warn_unreviewed_after_days >= 1",
            name="ck_ofp_unreviewed_days_min",
        ),
        sa.CheckConstraint(
            "warn_unreviewed_after_days IS NULL OR warn_unreviewed_after_days <= 3650",
            name="ck_ofp_unreviewed_days_max",
        ),
    )
    op.create_index(
        "ix_org_freshness_policies_org_id",
        "org_freshness_policies",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_org_freshness_policies_org_id", table_name="org_freshness_policies")
    op.drop_table("org_freshness_policies")
