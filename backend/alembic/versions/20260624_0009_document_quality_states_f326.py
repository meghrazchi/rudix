"""document quality workflow fields (F326)

Revision ID: 20260624_0009
Revises: 20260615_0008
Create Date: 2026-06-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260624_0009"
down_revision: str | None = "20260615_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("quality_state", sa.String(32), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("quality_notes", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "documents_quality_state_allowed",
        "documents",
        "quality_state IS NULL OR quality_state IN ('draft', 'verified', 'reviewed', 'unreviewed', 'stale', 'expired', 'deprecated', 'archived')",
    )
    op.create_index(
        "idx_documents_org_quality_state",
        "documents",
        ["organization_id", "quality_state"],
    )

    op.execute(
        sa.text(
            """
            UPDATE documents
            SET quality_state = CASE
                WHEN trust_status = 'draft' THEN 'draft'
                WHEN trust_status = 'verified' THEN 'verified'
                WHEN trust_status IN ('deprecated', 'superseded') THEN 'deprecated'
                WHEN trust_status = 'expired' THEN 'expired'
                WHEN trust_status = 'stale' THEN 'stale'
                WHEN review_status = 'archived' THEN 'archived'
                WHEN review_status = 'expired' OR expiry_date < CURRENT_DATE THEN 'expired'
                WHEN review_status = 'stale' OR review_date < CURRENT_DATE THEN 'stale'
                WHEN review_status = 'needs_review' OR review_due_date < CURRENT_DATE THEN 'unreviewed'
                WHEN trusted_at IS NOT NULL OR trusted_by_id IS NOT NULL THEN 'reviewed'
                WHEN review_owner_id IS NOT NULL THEN 'reviewed'
                ELSE 'unreviewed'
            END
            WHERE quality_state IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_documents_org_quality_state", table_name="documents")
    op.drop_constraint("documents_quality_state_allowed", "documents", type_="check")
    op.drop_column("documents", "quality_notes")
    op.drop_column("documents", "quality_state")
