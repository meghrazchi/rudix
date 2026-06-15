"""source freshness: trust_status, version_label, review_date and related fields on documents (F297)

Revision ID: 20260615_0008
Revises: 20260615_0007
Create Date: 2026-06-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260615_0008"
down_revision: str | None = "20260615_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "trust_status",
            sa.String(32),
            nullable=False,
            server_default="current",
        ),
    )
    op.add_column("documents", sa.Column("version_label", sa.String(32), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "superseded_by_document_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("documents", sa.Column("review_date", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("effective_date", sa.Date(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("trusted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "trusted_by_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("documents", sa.Column("stale_after_days", sa.Integer(), nullable=True))

    op.create_check_constraint(
        "documents_trust_status_allowed",
        "documents",
        "trust_status IN ('draft', 'current', 'verified', 'stale', 'deprecated', 'superseded', 'expired')",
    )
    op.create_index(
        "idx_documents_org_trust_status",
        "documents",
        ["organization_id", "trust_status"],
    )
    op.create_index(
        "idx_documents_org_review_date",
        "documents",
        ["organization_id", "review_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_documents_org_review_date", table_name="documents")
    op.drop_index("idx_documents_org_trust_status", table_name="documents")
    op.drop_constraint("documents_trust_status_allowed", "documents", type_="check")
    op.drop_column("documents", "stale_after_days")
    op.drop_column("documents", "trusted_by_id")
    op.drop_column("documents", "trusted_at")
    op.drop_column("documents", "effective_date")
    op.drop_column("documents", "review_date")
    op.drop_column("documents", "superseded_by_document_id")
    op.drop_column("documents", "version_label")
    op.drop_column("documents", "trust_status")
