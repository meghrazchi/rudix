"""agent timestamps timezone fix

Revision ID: 20260604_0002
Revises: 20260604_0001
Create Date: 2026-06-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0002"
down_revision: str | None = "20260604_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Convert all agent timestamp columns from TIMESTAMP WITHOUT TIME ZONE
    # to TIMESTAMP WITH TIME ZONE so timezone-aware UTC datetimes can be stored.
    # The runtime always passes datetime.now(UTC), which asyncpg rejects against
    # a plain TIMESTAMP column.
    op.alter_column(
        "agent_runs",
        "started_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_runs",
        "completed_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_runs",
        "cancelled_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_steps",
        "started_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_steps",
        "completed_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_tool_calls",
        "started_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_tool_calls",
        "completed_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_approvals",
        "expires_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_approvals",
        "decided_at",
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "agent_runs",
        "started_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_runs",
        "completed_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_runs",
        "cancelled_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_steps",
        "started_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_steps",
        "completed_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_tool_calls",
        "started_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_tool_calls",
        "completed_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_approvals",
        "expires_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
    op.alter_column(
        "agent_approvals",
        "decided_at",
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
    )
