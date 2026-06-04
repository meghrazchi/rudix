"""document language detection f230

Revision ID: 20260602_0019
Revises: 20260602_0018
Create Date: 2026-06-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0019"
down_revision: str | None = "20260602_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALID_SOURCES = ("upload_provided", "auto_detected", "admin_override")


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("language_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("language_source", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "documents_language_source_allowed",
        "documents",
        f"language_source IS NULL OR language_source IN ({', '.join(repr(s) for s in _VALID_SOURCES)})",
    )


def downgrade() -> None:
    op.drop_constraint("documents_language_source_allowed", "documents", type_="check")
    op.drop_column("documents", "language_source")
    op.drop_column("documents", "language_confidence")
