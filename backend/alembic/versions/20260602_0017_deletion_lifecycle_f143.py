"""data deletion lifecycle f143

Revision ID: 20260602_0017
Revises: 20260602_0016
Create Date: 2026-06-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0017"
down_revision: str | None = "20260602_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = (
    "uploaded",
    "processing",
    "indexed",
    "failed",
    "quarantined",
    "blocked",
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
    "delete_requested",
    "deleting",
    "deleted",
    "retained_by_policy",
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
            "deletion_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("deletion_hold_reason", sa.Text(), nullable=True),
    )

    op.create_index(
        "idx_documents_deletion_requested_at",
        "documents",
        ["organization_id", "deletion_requested_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_documents_deletion_requested_at", table_name="documents")
    op.drop_column("documents", "deletion_hold_reason")
    op.drop_column("documents", "deletion_requested_at")

    op.drop_constraint("documents_status_allowed", "documents", type_="check")
    op.create_check_constraint(
        "documents_status_allowed",
        "documents",
        f"status IN ({', '.join(repr(s) for s in _OLD_STATUSES)})",
    )
