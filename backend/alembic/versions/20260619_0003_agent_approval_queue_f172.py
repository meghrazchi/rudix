"""agent approval queue f172

Revision ID: 20260619_0003
Revises: 20260619_0002
Create Date: 2026-06-19

Extends agent_approvals for F172 — Agent human approval queue.

Adds the changes_requested status so approvers can request changes
from the agent without terminating the approval (run stays in
waiting_approval). Drops the old check constraint and recreates it
with the new value included.
"""

from __future__ import annotations

from alembic import op

revision = "20260619_0003"
down_revision = "20260619_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("agent_approvals_status_allowed", "agent_approvals", type_="check")
    op.create_check_constraint(
        "agent_approvals_status_allowed",
        "agent_approvals",
        "status IN ('pending', 'approved', 'rejected', 'changes_requested', 'expired', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("agent_approvals_status_allowed", "agent_approvals", type_="check")
    op.create_check_constraint(
        "agent_approvals_status_allowed",
        "agent_approvals",
        "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
    )
