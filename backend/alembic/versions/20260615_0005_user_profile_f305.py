"""user profile: avatar_url + preferences_json (F305)

Revision ID: 20260615_0005
Revises: 20260615_0004
Create Date: 2026-06-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260615_0005"
down_revision: str | None = "20260615_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(2048), nullable=True))
    op.add_column("users", sa.Column("preferences_json", sa.String(16384), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "preferences_json")
    op.drop_column("users", "avatar_url")
