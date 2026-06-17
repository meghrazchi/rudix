"""org-scoped MCP policy table (F175)

Revision ID: 20260620_0002
Revises: 20260620_0001
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260620_0002"
down_revision = "20260620_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_mcp_policies",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allowed_tools", sa.JSON(), nullable=True),
        sa.Column("capabilities_owner", sa.JSON(), nullable=True),
        sa.Column("capabilities_admin", sa.JSON(), nullable=True),
        sa.Column("capabilities_member", sa.JSON(), nullable=True),
        sa.Column("capabilities_viewer", sa.JSON(), nullable=True),
        sa.Column("rate_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "rate_limit_requests",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "rate_limit_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
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
        sa.CheckConstraint("rate_limit_requests >= 1", name="mcp_policy_rate_limit_requests_min"),
        sa.CheckConstraint(
            "rate_limit_requests <= 10000", name="mcp_policy_rate_limit_requests_max"
        ),
        sa.CheckConstraint(
            "rate_limit_window_seconds >= 1", name="mcp_policy_rate_limit_window_min"
        ),
        sa.CheckConstraint(
            "rate_limit_window_seconds <= 3600", name="mcp_policy_rate_limit_window_max"
        ),
    )
    op.create_index("idx_org_mcp_policies_org", "org_mcp_policies", ["organization_id"])


def downgrade() -> None:
    op.drop_index("idx_org_mcp_policies_org", table_name="org_mcp_policies")
    op.drop_table("org_mcp_policies")
