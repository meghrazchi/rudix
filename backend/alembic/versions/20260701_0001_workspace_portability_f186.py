"""workspace portability jobs for F186.

Revision ID: 20260701_0001
Revises: 20260628_0002
Create Date: 2026-07-01

Stores admin-requested workspace export/import jobs and sanitized JSON
artifacts. Raw document files, vector payloads, API key hashes, webhook secret
hashes, and credential material are intentionally outside this table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_0001"
down_revision: str | None = "20260628_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_portability_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("job_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("requested_sections", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("artifact", sa.JSON(), nullable=True),
        sa.Column("artifact_filename", sa.String(255), nullable=True),
        sa.Column("artifact_mime_type", sa.String(128), nullable=True),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=True),
        sa.Column("validation_errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            "job_type IN ('export', 'import')",
            name="workspace_portability_jobs_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'validated', 'completed', 'failed', "
            "'validation_failed', 'expired')",
            name="workspace_portability_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "artifact_size_bytes IS NULL OR artifact_size_bytes >= 0",
            name="workspace_portability_jobs_artifact_size_non_negative",
        ),
        sa.CheckConstraint(
            "records_processed >= 0",
            name="workspace_portability_jobs_records_processed_non_negative",
        ),
        sa.CheckConstraint(
            "records_failed >= 0",
            name="workspace_portability_jobs_records_failed_non_negative",
        ),
    )
    op.create_index(
        "idx_workspace_portability_jobs_org_created",
        "workspace_portability_jobs",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "idx_workspace_portability_jobs_org_status",
        "workspace_portability_jobs",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_workspace_portability_jobs_org_status",
        table_name="workspace_portability_jobs",
    )
    op.drop_index(
        "idx_workspace_portability_jobs_org_created",
        table_name="workspace_portability_jobs",
    )
    op.drop_table("workspace_portability_jobs")
