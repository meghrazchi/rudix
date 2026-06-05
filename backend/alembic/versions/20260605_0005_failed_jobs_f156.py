"""Failed job and retry dashboard

Revision ID: 20260605_0005
Revises: 20260605_0004
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0005"
down_revision: str | None = "20260605_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # failed_jobs — one row per terminal Celery task failure
    op.create_table(
        "failed_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="failed"),
        sa.Column("queue_name", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_retryable", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "attempt_count >= 0",
            name="failed_jobs_attempt_count_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_failed_jobs_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_failed_jobs"),
    )
    op.create_index("idx_failed_jobs_org_created", "failed_jobs", ["organization_id", "created_at"])
    op.create_index("idx_failed_jobs_org_status", "failed_jobs", ["organization_id", "status"])
    op.create_index("idx_failed_jobs_task_id", "failed_jobs", ["task_id"])

    # failed_job_audit_logs — immutable log of retry/cancel/resolve actions
    op.create_table(
        "failed_job_audit_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("failed_job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("performed_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["failed_job_id"],
            ["failed_jobs.id"],
            name="fk_failed_job_audit_logs_job_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_failed_job_audit_logs_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["performed_by_id"],
            ["users.id"],
            name="fk_failed_job_audit_logs_performed_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_failed_job_audit_logs"),
    )
    op.create_index(
        "idx_failed_job_audit_logs_job_id", "failed_job_audit_logs", ["failed_job_id"]
    )
    op.create_index(
        "idx_failed_job_audit_logs_org_created",
        "failed_job_audit_logs",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_failed_job_audit_logs_org_created", table_name="failed_job_audit_logs")
    op.drop_index("idx_failed_job_audit_logs_job_id", table_name="failed_job_audit_logs")
    op.drop_table("failed_job_audit_logs")

    op.drop_index("idx_failed_jobs_task_id", table_name="failed_jobs")
    op.drop_index("idx_failed_jobs_org_status", table_name="failed_jobs")
    op.drop_index("idx_failed_jobs_org_created", table_name="failed_jobs")
    op.drop_table("failed_jobs")
