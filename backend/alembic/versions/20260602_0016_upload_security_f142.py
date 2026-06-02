"""upload security hardening f142

Revision ID: 20260602_0016
Revises: 20260602_0015
Create Date: 2026-06-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0016"
down_revision: str | None = "20260602_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = (
    "uploaded",
    "processing",
    "indexed",
    "failed",
    "deleting",
    "deleted",
)
_NEW_STATUSES = (
    "uploaded",
    "processing",
    "indexed",
    "failed",
    "quarantined",
    "blocked",
    "deleting",
    "deleted",
)


def upgrade() -> None:
    op.drop_constraint("documents_status_allowed", "documents", type_="check")
    op.create_check_constraint(
        "documents_status_allowed",
        "documents",
        f"status IN ({', '.join(repr(s) for s in _NEW_STATUSES)})",
    )

    op.add_column(
        "documents",
        sa.Column(
            "duplicate_of_document_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        op.f("fk_documents_duplicate_of_document_id_documents"),
        "documents",
        "documents",
        ["duplicate_of_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_documents_duplicate_of",
        "documents",
        ["duplicate_of_document_id"],
        unique=False,
    )

    op.add_column(
        "documents",
        sa.Column("security_scan_result", sa.JSON(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("dlp_scan_result", sa.JSON(), nullable=True),
    )

    op.create_index(
        "idx_documents_org_checksum",
        "documents",
        ["organization_id", "checksum"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_documents_org_checksum", table_name="documents")
    op.drop_index("idx_documents_duplicate_of", table_name="documents")
    op.drop_constraint(
        op.f("fk_documents_duplicate_of_document_id_documents"),
        "documents",
        type_="foreignkey",
    )
    op.drop_column("documents", "dlp_scan_result")
    op.drop_column("documents", "security_scan_result")
    op.drop_column("documents", "duplicate_of_document_id")

    op.drop_constraint("documents_status_allowed", "documents", type_="check")
    op.create_check_constraint(
        "documents_status_allowed",
        "documents",
        f"status IN ({', '.join(repr(s) for s in _OLD_STATUSES)})",
    )
