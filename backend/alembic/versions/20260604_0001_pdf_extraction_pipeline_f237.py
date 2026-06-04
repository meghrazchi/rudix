"""pdf extraction pipeline f237

Revision ID: 20260604_0001
Revises: 20260602_0020
Create Date: 2026-06-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0001"
down_revision: str | None = "20260602_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Structured extraction diagnostics from the PDF extraction pipeline (F237).
    # Stores document profile, block counts, per-page signals, and warnings.
    op.add_column(
        "documents",
        sa.Column("extraction_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "extraction_snapshot")
