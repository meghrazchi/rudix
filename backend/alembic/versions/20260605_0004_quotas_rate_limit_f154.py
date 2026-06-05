"""Quotas and rate-limit management

Revision ID: 20260605_0004
Revises: 20260605_0003
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0004"
down_revision: str | None = "20260605_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # org_quota_policy — one row per org, stores limits per quota type as JSONB
    op.create_table(
        "org_quota_policy",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "limits",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_id", sa.Uuid(as_uuid=True), nullable=True),
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
        sa.CheckConstraint("version >= 1", name="org_quota_policy_version_positive"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_quota_policy_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_org_quota_policy_updated_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_quota_policy"),
        sa.UniqueConstraint("organization_id", name="uq_org_quota_policy_org"),
    )
    op.create_index("idx_org_quota_policy_org_id", "org_quota_policy", ["organization_id"])

    # org_quota_usage — current usage counter per org per quota type, reset on window expiry
    op.create_table(
        "org_quota_usage",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("quota_type", sa.String(length=64), nullable=False),
        sa.Column("current_value", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "period_start",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("next_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "current_value >= 0",
            name="org_quota_usage_current_value_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_quota_usage_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_quota_usage"),
        sa.UniqueConstraint(
            "organization_id",
            "quota_type",
            name="uq_org_quota_usage_org_type",
        ),
    )
    op.create_index("idx_org_quota_usage_org_id", "org_quota_usage", ["organization_id"])
    op.create_index(
        "idx_org_quota_usage_org_type",
        "org_quota_usage",
        ["organization_id", "quota_type"],
    )

    # org_quota_override — per-user or org-wide hard limit override
    op.create_table(
        "org_quota_override",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("quota_type", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("hard_limit_override", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "hard_limit_override IS NULL OR hard_limit_override >= 0",
            name="org_quota_override_hard_limit_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_quota_override_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_org_quota_override_target_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_org_quota_override_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_quota_override"),
    )
    op.create_index("idx_org_quota_override_org_id", "org_quota_override", ["organization_id"])
    op.create_index(
        "idx_org_quota_override_org_type",
        "org_quota_override",
        ["organization_id", "quota_type"],
    )

    # org_quota_change_log — immutable audit trail of policy changes
    op.create_table(
        "org_quota_change_log",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("org_quota_policy_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "policy_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("change_note", sa.String(length=1000), nullable=True),
        sa.Column("changed_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="org_quota_change_log_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_quota_change_log_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_quota_policy_id"],
            ["org_quota_policy.id"],
            name="fk_org_quota_change_log_policy_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name="fk_org_quota_change_log_changed_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_quota_change_log"),
        sa.UniqueConstraint(
            "organization_id",
            "version_number",
            name="uq_org_quota_change_log_org_version",
        ),
    )
    op.create_index(
        "idx_org_quota_change_log_org_id",
        "org_quota_change_log",
        ["organization_id"],
    )
    op.create_index(
        "idx_org_quota_change_log_org_version",
        "org_quota_change_log",
        ["organization_id", "version_number"],
    )


def downgrade() -> None:
    op.drop_index("idx_org_quota_change_log_org_version", table_name="org_quota_change_log")
    op.drop_index("idx_org_quota_change_log_org_id", table_name="org_quota_change_log")
    op.drop_table("org_quota_change_log")

    op.drop_index("idx_org_quota_override_org_type", table_name="org_quota_override")
    op.drop_index("idx_org_quota_override_org_id", table_name="org_quota_override")
    op.drop_table("org_quota_override")

    op.drop_index("idx_org_quota_usage_org_type", table_name="org_quota_usage")
    op.drop_index("idx_org_quota_usage_org_id", table_name="org_quota_usage")
    op.drop_table("org_quota_usage")

    op.drop_index("idx_org_quota_policy_org_id", table_name="org_quota_policy")
    op.drop_table("org_quota_policy")
