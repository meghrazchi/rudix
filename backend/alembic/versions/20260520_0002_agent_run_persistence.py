"""agent run persistence and trace schema

Revision ID: 20260520_0002
Revises: 20260507_0001
Create Date: 2026-05-20 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260520_0002"
down_revision: str | None = "20260507_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("max_steps", sa.Integer(), nullable=True),
        sa.Column("max_parallel_tool_calls", sa.Integer(), nullable=True),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("costs", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("observations", sa.JSON(), nullable=False),
        sa.Column("total_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_request_id", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'planning', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_agent_runs_agent_runs_status_allowed"),
        ),
        sa.CheckConstraint("surface IN ('api', 'mcp')", name=op.f("ck_agent_runs_agent_runs_surface_allowed")),
        sa.CheckConstraint(
            "max_steps IS NULL OR max_steps >= 0",
            name=op.f("ck_agent_runs_agent_runs_max_steps_non_negative"),
        ),
        sa.CheckConstraint(
            "max_parallel_tool_calls IS NULL OR max_parallel_tool_calls >= 0",
            name=op.f("ck_agent_runs_agent_runs_max_parallel_tool_calls_non_negative"),
        ),
        sa.CheckConstraint(
            "total_cost_usd IS NULL OR total_cost_usd >= 0",
            name=op.f("ck_agent_runs_agent_runs_total_cost_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_agent_runs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_runs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index("idx_agent_runs_org_status", "agent_runs", ["organization_id", "status"], unique=False)
    op.create_index(
        "idx_agent_runs_org_user_created",
        "agent_runs",
        ["organization_id", "user_id", "created_at"],
        unique=False,
    )
    op.create_index("idx_agent_runs_trace_request_id", "agent_runs", ["trace_request_id"], unique=False)

    op.create_table(
        "agent_steps",
        sa.Column("agent_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("observation", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'completed', 'failed', 'skipped', 'cancelled')",
            name=op.f("ck_agent_steps_agent_steps_status_allowed"),
        ),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_agent_steps_agent_steps_sequence_non_negative")),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name=op.f("ck_agent_steps_agent_steps_duration_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_steps_agent_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_agent_steps_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_steps_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_steps")),
        sa.UniqueConstraint("agent_run_id", "sequence", name=op.f("uq_agent_steps_agent_run_id")),
    )
    op.create_index("idx_agent_steps_org_status", "agent_steps", ["organization_id", "status"], unique=False)
    op.create_index("idx_agent_steps_run_sequence", "agent_steps", ["agent_run_id", "sequence"], unique=False)

    op.create_table(
        "agent_tool_calls",
        sa.Column("agent_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("agent_step_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("call_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("effect_policy", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=128), nullable=True),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=False),
        sa.Column("input_size_bytes", sa.Integer(), nullable=True),
        sa.Column("output_size_bytes", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("surface IN ('api', 'mcp')", name=op.f("ck_agent_tool_calls_agent_tool_calls_surface_allowed")),
        sa.CheckConstraint(
            "effect_policy IN ('read_only', 'side_effect')",
            name=op.f("ck_agent_tool_calls_agent_tool_calls_effect_policy_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_agent_tool_calls_agent_tool_calls_status_allowed"),
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name=op.f("ck_agent_tool_calls_agent_tool_calls_attempt_number_positive"),
        ),
        sa.CheckConstraint(
            "input_size_bytes IS NULL OR input_size_bytes >= 0",
            name=op.f("ck_agent_tool_calls_agent_tool_calls_input_size_non_negative"),
        ),
        sa.CheckConstraint(
            "output_size_bytes IS NULL OR output_size_bytes >= 0",
            name=op.f("ck_agent_tool_calls_agent_tool_calls_output_size_non_negative"),
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name=op.f("ck_agent_tool_calls_agent_tool_calls_latency_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_tool_calls_agent_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_step_id"],
            ["agent_steps.id"],
            name=op.f("fk_agent_tool_calls_agent_step_id_agent_steps"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_agent_tool_calls_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_tool_calls_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_tool_calls")),
        sa.UniqueConstraint("call_id", name=op.f("uq_agent_tool_calls_call_id")),
    )
    op.create_index("idx_agent_tool_calls_org_status", "agent_tool_calls", ["organization_id", "status"], unique=False)
    op.create_index("idx_agent_tool_calls_run_status", "agent_tool_calls", ["agent_run_id", "status"], unique=False)
    op.create_index("idx_agent_tool_calls_tool_name", "agent_tool_calls", ["tool_name"], unique=False)

    op.create_table(
        "agent_approvals",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("agent_step_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("tool_call_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_summary", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("decision_payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name=op.f("ck_agent_approvals_agent_approvals_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_agent_approvals_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_approvals_agent_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_step_id"],
            ["agent_steps.id"],
            name=op.f("fk_agent_approvals_agent_step_id_agent_steps"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["agent_tool_calls.id"],
            name=op.f("fk_agent_approvals_tool_call_id_agent_tool_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_agent_approvals_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("fk_agent_approvals_decided_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_approvals")),
    )
    op.create_index("idx_agent_approvals_org_status", "agent_approvals", ["organization_id", "status"], unique=False)
    op.create_index("idx_agent_approvals_run_status", "agent_approvals", ["agent_run_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_agent_approvals_run_status", table_name="agent_approvals")
    op.drop_index("idx_agent_approvals_org_status", table_name="agent_approvals")
    op.drop_table("agent_approvals")

    op.drop_index("idx_agent_tool_calls_tool_name", table_name="agent_tool_calls")
    op.drop_index("idx_agent_tool_calls_run_status", table_name="agent_tool_calls")
    op.drop_index("idx_agent_tool_calls_org_status", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")

    op.drop_index("idx_agent_steps_run_sequence", table_name="agent_steps")
    op.drop_index("idx_agent_steps_org_status", table_name="agent_steps")
    op.drop_table("agent_steps")

    op.drop_index("idx_agent_runs_trace_request_id", table_name="agent_runs")
    op.drop_index("idx_agent_runs_org_user_created", table_name="agent_runs")
    op.drop_index("idx_agent_runs_org_status", table_name="agent_runs")
    op.drop_table("agent_runs")
