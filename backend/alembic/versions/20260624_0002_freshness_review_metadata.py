"""freshness review metadata on documents, collections, and source documents

Revision ID: 20260624_0002
Revises: 20260624_0001
Create Date: 2026-06-24 00:02:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260624_0002"
down_revision: str | None = "20260624_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REVIEW_STATUS_ALLOWED = (
    "current",
    "trusted",
    "needs_review",
    "stale",
    "expired",
    "archived",
)
_REVIEW_STATUS_SQL = ", ".join(f"'{value}'" for value in _REVIEW_STATUS_ALLOWED)


def _add_review_columns(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column(
            "review_status",
            sa.String(32),
            nullable=False,
            server_default="current",
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "review_owner_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(table_name, sa.Column("review_due_date", sa.Date(), nullable=True))
    op.add_column(table_name, sa.Column("expiry_date", sa.Date(), nullable=True))
    op.add_column(table_name, sa.Column("trust_level", sa.String(32), nullable=True))
    op.create_check_constraint(
        f"{table_name}_review_status_allowed",
        table_name,
        f"review_status IN ({_REVIEW_STATUS_SQL})",
    )
    op.create_index(
        f"idx_{table_name}_org_review_status",
        table_name,
        ["organization_id", "review_status"],
    )
    op.create_index(
        f"idx_{table_name}_org_review_due_date",
        table_name,
        ["organization_id", "review_due_date"],
    )


def _drop_review_columns(table_name: str) -> None:
    op.drop_index(f"idx_{table_name}_org_review_due_date", table_name=table_name)
    op.drop_index(f"idx_{table_name}_org_review_status", table_name=table_name)
    op.drop_constraint(
        f"{table_name}_review_status_allowed",
        table_name,
        type_="check",
    )
    op.drop_column(table_name, "trust_level")
    op.drop_column(table_name, "expiry_date")
    op.drop_column(table_name, "review_due_date")
    op.drop_column(table_name, "review_owner_id")
    op.drop_column(table_name, "review_status")


def upgrade() -> None:
    for table_name in ("documents", "collections", "source_documents"):
        _add_review_columns(table_name)


def downgrade() -> None:
    for table_name in ("source_documents", "collections", "documents"):
        _drop_review_columns(table_name)
