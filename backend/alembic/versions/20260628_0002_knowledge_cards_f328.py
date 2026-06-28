"""Add deprecated status and deprecated_at to verified_answers (F328).

Revision ID: 20260628_0002
Revises: 20260630_0003
Create Date: 2026-06-28

Extends the knowledge-card status machine with a 'deprecated' state and
records the timestamp when a card was deprecated. Also adds a
'restored_at' column so restore-from-archive events are traceable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260628_0002"
down_revision: str | None = "20260630_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drop the old CHECK constraint (only 5 statuses).
    with op.batch_alter_table("verified_answers") as batch_op:
        batch_op.drop_constraint(
            "verified_answers_status_allowed", type_="check"
        )

    # 2. Re-add it with 'deprecated' included.
    with op.batch_alter_table("verified_answers") as batch_op:
        batch_op.create_check_constraint(
            "verified_answers_status_allowed",
            "status IN ('draft','pending_review','approved','published','archived','deprecated')",
        )
        batch_op.add_column(
            sa.Column(
                "deprecated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "restored_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("verified_answers") as batch_op:
        batch_op.drop_column("restored_at")
        batch_op.drop_column("deprecated_at")
        batch_op.drop_constraint(
            "verified_answers_status_allowed", type_="check"
        )

    with op.batch_alter_table("verified_answers") as batch_op:
        batch_op.create_check_constraint(
            "verified_answers_status_allowed",
            "status IN ('draft','pending_review','approved','published','archived')",
        )
