"""safety eval suite f146

Revision ID: 20260602_0018
Revises: 20260602_0017
Create Date: 2026-06-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0018"
down_revision: str | None = "20260602_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VIOLATION_TYPES = (
    "injection",
    "cross_tenant_leakage",
    "private_source_exposure",
    "unsupported_claims",
    "malicious_document",
    "unsafe_transform",
)
_RUN_STATUSES = ("queued", "running", "completed", "failed")
_SEVERITIES = ("critical", "high", "medium", "low")


def upgrade() -> None:
    op.create_table(
        "safety_eval_cases",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suite_name", sa.String(255), nullable=False),
        sa.Column("violation_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False, server_default="high"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"violation_type IN ({', '.join(repr(v) for v in _VIOLATION_TYPES)})",
            name="safety_eval_cases_violation_type_allowed",
        ),
        sa.CheckConstraint(
            f"severity IN ({', '.join(repr(s) for s in _SEVERITIES)})",
            name="safety_eval_cases_severity_allowed",
        ),
    )
    op.create_index(
        "idx_safety_eval_cases_org_suite",
        "safety_eval_cases",
        ["organization_id", "suite_name"],
    )

    op.create_table(
        "safety_eval_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suite_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pass_count", sa.Integer(), nullable=True),
        sa.Column("fail_count", sa.Integer(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in _RUN_STATUSES)})",
            name="safety_eval_runs_status_allowed",
        ),
    )
    op.create_index(
        "idx_safety_eval_runs_org_created",
        "safety_eval_runs",
        ["organization_id", "created_at"],
    )

    op.create_table(
        "safety_eval_results",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "safety_eval_run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("safety_eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "safety_eval_case_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("safety_eval_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("violation_detected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("violation_type", sa.String(64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_safety_eval_results_run_id",
        "safety_eval_results",
        ["safety_eval_run_id"],
    )
    op.create_index(
        "idx_safety_eval_results_case_id",
        "safety_eval_results",
        ["safety_eval_case_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_safety_eval_results_case_id", table_name="safety_eval_results")
    op.drop_index("idx_safety_eval_results_run_id", table_name="safety_eval_results")
    op.drop_table("safety_eval_results")

    op.drop_index("idx_safety_eval_runs_org_created", table_name="safety_eval_runs")
    op.drop_table("safety_eval_runs")

    op.drop_index("idx_safety_eval_cases_org_suite", table_name="safety_eval_cases")
    op.drop_table("safety_eval_cases")
