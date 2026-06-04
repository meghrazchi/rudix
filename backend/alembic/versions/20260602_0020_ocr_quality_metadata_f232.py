"""ocr quality metadata f232

Revision ID: 20260602_0020
Revises: 20260602_0019
Create Date: 2026-06-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0020"
down_revision: str | None = "20260602_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Per-document OCR language override (comma-separated Tesseract codes, e.g. "eng,deu").
    op.add_column(
        "documents",
        sa.Column("ocr_languages_override", sa.String(255), nullable=True),
    )
    # Snapshot of OCR quality metrics from the most recent pipeline run.
    op.add_column(
        "documents",
        sa.Column("ocr_quality_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "ocr_quality_snapshot")
    op.drop_column("documents", "ocr_languages_override")
