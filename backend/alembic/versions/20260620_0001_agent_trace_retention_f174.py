"""agent trace share tokens and retention policy (F174)

Revision ID: 20260620_0001
Revises: 20260619_0004
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260620_0001"
down_revision = "20260619_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_trace_retention_policies",
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
        sa.Column("retain_days", sa.Integer(), nullable=False, server_default=sa.text("90")),
        sa.Column("redact_prompts", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "redact_raw_content", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "redact_tool_arguments",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        sa.CheckConstraint("retain_days >= 1", name="trace_retention_retain_days_positive"),
        sa.CheckConstraint("retain_days <= 3650", name="trace_retention_retain_days_max_ten_years"),
    )
    op.create_index(
        "idx_trace_retention_org",
        "agent_trace_retention_policies",
        ["organization_id"],
    )

    op.create_table(
        "agent_trace_share_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "idx_trace_share_tokens_org",
        "agent_trace_share_tokens",
        ["organization_id"],
    )
    op.create_index(
        "idx_trace_share_tokens_run",
        "agent_trace_share_tokens",
        ["agent_run_id"],
    )
    op.create_index(
        "idx_trace_share_tokens_hash",
        "agent_trace_share_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_trace_share_tokens_hash", table_name="agent_trace_share_tokens")
    op.drop_index("idx_trace_share_tokens_run", table_name="agent_trace_share_tokens")
    op.drop_index("idx_trace_share_tokens_org", table_name="agent_trace_share_tokens")
    op.drop_table("agent_trace_share_tokens")
    op.drop_index("idx_trace_retention_org", table_name="agent_trace_retention_policies")
    op.drop_table("agent_trace_retention_policies")
