"""quality gate release gates

Revision ID: 20260604_0004
Revises: 20260604_0003
Create Date: 2026-06-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0004"
down_revision: str | None = "20260604_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quality_gates",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thresholds", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("baseline_evaluation_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("baseline_safety_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_quality_gates_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_evaluation_run_id"],
            ["evaluation_runs.id"],
            name="fk_quality_gates_baseline_evaluation_run_id_evaluation_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_safety_run_id"],
            ["safety_eval_runs.id"],
            name="fk_quality_gates_baseline_safety_run_id_safety_eval_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_quality_gates_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quality_gates"),
    )
    op.create_index(
        "idx_quality_gates_organization_id",
        "quality_gates",
        ["organization_id"],
    )

    op.create_table(
        "quality_gate_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("quality_gate_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evaluation_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("safety_eval_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("triggered_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("overridden_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
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
            "verdict IN ('passed', 'failed', 'overridden')",
            name="quality_gate_runs_verdict_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["quality_gate_id"],
            ["quality_gates.id"],
            name="fk_quality_gate_runs_quality_gate_id_quality_gates",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            name="fk_quality_gate_runs_evaluation_run_id_evaluation_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["safety_eval_run_id"],
            ["safety_eval_runs.id"],
            name="fk_quality_gate_runs_safety_eval_run_id_safety_eval_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_id"],
            ["users.id"],
            name="fk_quality_gate_runs_triggered_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["overridden_by_id"],
            ["users.id"],
            name="fk_quality_gate_runs_overridden_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quality_gate_runs"),
    )
    op.create_index(
        "idx_quality_gate_runs_gate",
        "quality_gate_runs",
        ["quality_gate_id", "created_at"],
    )
    op.create_index(
        "idx_quality_gate_runs_eval_run",
        "quality_gate_runs",
        ["evaluation_run_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_quality_gate_runs_eval_run", table_name="quality_gate_runs")
    op.drop_index("idx_quality_gate_runs_gate", table_name="quality_gate_runs")
    op.drop_table("quality_gate_runs")

    op.drop_index("idx_quality_gates_organization_id", table_name="quality_gates")
    op.drop_table("quality_gates")
