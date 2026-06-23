"""ab testing prompt and retrieval profile f304

Revision ID: 20260618_0001
Revises: 20260617_0002
Create Date: 2026-06-18

Adds four tables for F304 A/B experiment management:
  - ab_experiments        (experiment definition, org-scoped)
  - ab_experiment_variants (variant: rag_profile + prompt_template version + model key)
  - ab_experiment_runs    (one run per experiment execution)
  - ab_experiment_variant_runs (per-variant evaluation run + metrics cache)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260618_0001"
down_revision = "20260617_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # ab_experiments
    # ------------------------------------------------------------------ #
    op.create_table(
        "ab_experiments",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("evaluation_set_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column(
            "metrics_config",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluation_set_id"], ["evaluation_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('draft', 'running', 'completed', 'failed')",
            name="ab_experiments_status_allowed",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ab_experiments_organization_id", "ab_experiments", ["organization_id"])

    # ------------------------------------------------------------------ #
    # ab_experiment_variants
    # ------------------------------------------------------------------ #
    op.create_table(
        "ab_experiment_variants",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experiment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rag_profile_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("rag_profile_version", sa.Integer(), nullable=True),
        sa.Column("prompt_template_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("model_profile_key", sa.String(length=64), nullable=True),
        sa.Column(
            "config_snapshot",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "approval_status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column("approved_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["experiment_id"], ["ab_experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rag_profile_id"], ["rag_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["prompt_template_version_id"], ["prompt_template_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ab_experiment_variants_approval_allowed",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_ab_experiment_variants_experiment_id", "ab_experiment_variants", ["experiment_id"]
    )

    # ------------------------------------------------------------------ #
    # ab_experiment_runs
    # ------------------------------------------------------------------ #
    op.create_table(
        "ab_experiment_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experiment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column(
            "comparison_report",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("triggered_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["experiment_id"], ["ab_experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["triggered_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('draft', 'running', 'completed', 'failed')",
            name="ab_experiment_runs_status_allowed",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_ab_experiment_runs_experiment_id",
        "ab_experiment_runs",
        ["experiment_id", "created_at"],
    )

    # ------------------------------------------------------------------ #
    # ab_experiment_variant_runs
    # ------------------------------------------------------------------ #
    op.create_table(
        "ab_experiment_variant_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experiment_run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("variant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evaluation_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column(
            "metrics_summary",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error_detail", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["experiment_run_id"], ["ab_experiment_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["variant_id"], ["ab_experiment_variants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evaluation_run_id"], ["evaluation_runs.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ab_experiment_variant_runs_status_allowed",
        ),
        sa.UniqueConstraint(
            "experiment_run_id",
            "variant_id",
            name="uq_ab_variant_runs_run_variant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_ab_variant_runs_experiment_run_id",
        "ab_experiment_variant_runs",
        ["experiment_run_id"],
    )
    op.create_index(
        "idx_ab_variant_runs_evaluation_run_id",
        "ab_experiment_variant_runs",
        ["evaluation_run_id"],
    )


def downgrade() -> None:
    op.drop_table("ab_experiment_variant_runs")
    op.drop_table("ab_experiment_runs")
    op.drop_table("ab_experiment_variants")
    op.drop_table("ab_experiments")
