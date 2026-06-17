"""agent tool policy and budget overrides (F173)

Revision ID: 20260619_0004
Revises: 20260619_0003
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260619_0004"
down_revision = "20260619_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_policy_overrides",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tool_name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("approval_required", sa.Boolean(), nullable=True),
        sa.Column("required_roles", sa.JSON(), nullable=True),
        sa.Column("max_calls_per_run", sa.Integer(), nullable=True),
        sa.Column("max_input_bytes", sa.Integer(), nullable=True),
        sa.Column("max_output_bytes", sa.Integer(), nullable=True),
        sa.Column("timeout_ms", sa.Integer(), nullable=True),
        sa.Column("max_retry_attempts", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("organization_id", "tool_name", name="uq_agent_tool_policy_org_tool"),
        sa.CheckConstraint(
            "max_calls_per_run IS NULL OR max_calls_per_run >= 1",
            name="agent_tool_policy_max_calls_positive",
        ),
        sa.CheckConstraint(
            "max_input_bytes IS NULL OR max_input_bytes >= 512",
            name="agent_tool_policy_input_bytes_min",
        ),
        sa.CheckConstraint(
            "max_output_bytes IS NULL OR max_output_bytes >= 512",
            name="agent_tool_policy_output_bytes_min",
        ),
        sa.CheckConstraint(
            "timeout_ms IS NULL OR timeout_ms >= 100",
            name="agent_tool_policy_timeout_min",
        ),
        sa.CheckConstraint(
            "max_retry_attempts IS NULL OR max_retry_attempts >= 0",
            name="agent_tool_policy_retry_non_negative",
        ),
    )
    op.create_index(
        "idx_agent_tool_policy_org",
        "agent_tool_policy_overrides",
        ["organization_id"],
    )

    op.add_column(
        "agent_runs",
        sa.Column("policy_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "policy_snapshot")
    op.drop_index("idx_agent_tool_policy_org", table_name="agent_tool_policy_overrides")
    op.drop_table("agent_tool_policy_overrides")
