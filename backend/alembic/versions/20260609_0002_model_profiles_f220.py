"""Model profiles and provider policy (F220)

Adds org_model_profiles and org_model_profile_change_log tables for
task-typed model profile configuration with full change history.

Revision ID: 20260609_0002
Revises: 20260609_0001
Create Date: 2026-06-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260609_0002"
down_revision: str | None = "20260609_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_model_profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_name", sa.String(length=100), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("base_model", sa.String(length=255), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Numeric(precision=5, scale=3), nullable=True),
        sa.Column("json_mode", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("streaming", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("fallback_provider_key", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "is_experimental", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("cost_metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "organization_id",
            "task_type",
            name="uq_org_model_profiles_org_task",
        ),
        sa.CheckConstraint(
            "max_tokens IS NULL OR max_tokens >= 1",
            name="org_model_profiles_max_tokens_positive",
        ),
        sa.CheckConstraint(
            "temperature IS NULL OR (temperature >= 0 AND temperature <= 2)",
            name="org_model_profiles_temperature_range",
        ),
        sa.CheckConstraint(
            "context_window IS NULL OR context_window >= 1",
            name="org_model_profiles_context_window_positive",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="org_model_profiles_version_positive",
        ),
    )
    op.create_index("idx_org_model_profiles_org_id", "org_model_profiles", ["organization_id"])
    op.create_index(
        "idx_org_model_profiles_org_task",
        "org_model_profiles",
        ["organization_id", "task_type"],
    )

    op.create_table(
        "org_model_profile_change_log",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_model_profile_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("org_model_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("profile_snapshot", JSONB(), nullable=False),
        sa.Column("change_note", sa.String(length=1000), nullable=True),
        sa.Column(
            "changed_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "organization_id",
            "task_type",
            "version_number",
            name="uq_org_model_profile_change_log_org_task_version",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="org_model_profile_change_log_version_positive",
        ),
    )
    op.create_index(
        "idx_org_model_profile_change_log_org_id",
        "org_model_profile_change_log",
        ["organization_id"],
    )
    op.create_index(
        "idx_org_model_profile_change_log_org_task",
        "org_model_profile_change_log",
        ["organization_id", "task_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_org_model_profile_change_log_org_task",
        table_name="org_model_profile_change_log",
    )
    op.drop_index(
        "idx_org_model_profile_change_log_org_id",
        table_name="org_model_profile_change_log",
    )
    op.drop_table("org_model_profile_change_log")

    op.drop_index("idx_org_model_profiles_org_task", table_name="org_model_profiles")
    op.drop_index("idx_org_model_profiles_org_id", table_name="org_model_profiles")
    op.drop_table("org_model_profiles")
