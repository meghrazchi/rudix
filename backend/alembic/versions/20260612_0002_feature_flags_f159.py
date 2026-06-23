"""feature_flags_f159

Revision ID: 20260612_0002
Revises: 20260612_0001
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260612_0002"
down_revision: str | None = "20260612_0001"


def upgrade() -> None:
    op.create_table(
        "org_feature_flag_overrides",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("flag_name", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("overridden_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "overridden_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["overridden_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "flag_name",
            name="uq_org_feature_flag_overrides_org_flag",
        ),
    )
    op.create_index(
        "idx_org_feature_flag_overrides_org_id",
        "org_feature_flag_overrides",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_org_feature_flag_overrides_org_id",
        table_name="org_feature_flag_overrides",
    )
    op.drop_table("org_feature_flag_overrides")
