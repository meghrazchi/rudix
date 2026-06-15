"""OCR quality scoring: ocr_quality_status/ocr_avg_confidence on documents, ocr_confidence on document_pages (F299)

Revision ID: 20260617_0001
Revises: 20260616_0001
Create Date: 2026-06-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0001"
down_revision: str | None = "20260616_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("ocr_quality_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("ocr_avg_confidence", sa.Float, nullable=True),
    )
    op.create_check_constraint(
        "documents_ocr_quality_status_allowed",
        "documents",
        "ocr_quality_status IS NULL OR ocr_quality_status IN ('high', 'medium', 'low', 'failed', 'not_required')",
    )
    op.create_index(
        "idx_documents_org_ocr_quality_status",
        "documents",
        ["organization_id", "ocr_quality_status"],
    )

    op.add_column(
        "document_pages",
        sa.Column("ocr_confidence", sa.Float, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_pages", "ocr_confidence")
    op.drop_index("idx_documents_org_ocr_quality_status", table_name="documents")
    op.drop_constraint("documents_ocr_quality_status_allowed", "documents", type_="check")
    op.drop_column("documents", "ocr_avg_confidence")
    op.drop_column("documents", "ocr_quality_status")
