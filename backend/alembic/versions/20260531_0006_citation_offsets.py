"""citation highlight offsets

Revision ID: 20260531_0006
Revises: 20260531_0005
Create Date: 2026-05-31 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0006"
down_revision: str | None = "20260531_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("citations", sa.Column("start_offset", sa.Integer(), nullable=True))
    op.add_column("citations", sa.Column("end_offset", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("citations", "end_offset")
    op.drop_column("citations", "start_offset")
