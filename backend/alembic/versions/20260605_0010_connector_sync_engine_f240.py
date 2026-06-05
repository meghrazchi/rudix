"""connector sync engine: trigger_type and celery_task_id on sync runs

Revision ID: 20260605_0010
Revises: 20260605_0009
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260605_0010"
down_revision: str | None = "20260605_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "connector_sync_runs",
        sa.Column(
            "trigger_type",
            sa.String(length=32),
            nullable=False,
            server_default="scheduled",
        ),
    )
    op.add_column(
        "connector_sync_runs",
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "idx_connector_sync_runs_connection_status",
        "connector_sync_runs",
        ["connection_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_connector_sync_runs_connection_status",
        table_name="connector_sync_runs",
    )
    op.drop_column("connector_sync_runs", "celery_task_id")
    op.drop_column("connector_sync_runs", "trigger_type")
