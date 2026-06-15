"""pipeline_runs + pipeline_events: started_at/completed_at to TIMESTAMPTZ

Revision ID: 20260615_0007
Revises: 20260615_0006
Create Date: 2026-06-15 00:00:00.000000

Workers pass UTC-aware datetimes; asyncpg rejects them against TIMESTAMP WITHOUT
TIME ZONE columns. Converting to TIMESTAMPTZ (with time zone) fixes the mismatch.
Existing rows are safe: PostgreSQL reinterprets the stored UTC values as-is.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260615_0007"
down_revision: str | None = "20260615_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "pipeline_runs",
        "started_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "pipeline_runs",
        "completed_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "pipeline_events",
        "started_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "pipeline_events",
        "completed_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "pipeline_events",
        "completed_at",
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "pipeline_events",
        "started_at",
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "pipeline_runs",
        "completed_at",
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "pipeline_runs",
        "started_at",
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
