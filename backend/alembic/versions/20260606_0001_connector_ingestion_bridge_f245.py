"""connector ingestion bridge: new document statuses, ingestion_source, connector_external_item_id

Revision ID: 20260606_0001
Revises: 20260605_0010
Create Date: 2026-06-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260606_0001"
down_revision: str | None = "20260605_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. Widen the documents.status CHECK constraint to include connector
    #    file ingestion statuses introduced in F245.
    # -----------------------------------------------------------------------
    op.drop_constraint("documents_status_allowed", "documents", type_="check")
    op.create_check_constraint(
        "documents_status_allowed",
        "documents",
        "status IN ("
        "'uploaded', 'processing', 'indexed', 'failed', 'quarantined', 'blocked', "
        "'delete_requested', 'deleting', 'deleted', 'retained_by_policy', "
        "'pending_scan', 'infected', 'extraction_failed', 'ocr_applied', "
        "'skipped', 'unsupported'"
        ")",
    )

    # -----------------------------------------------------------------------
    # 2. ingestion_source: distinguishes manual uploads from connector files.
    # -----------------------------------------------------------------------
    op.add_column(
        "documents",
        sa.Column("ingestion_source", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "documents_ingestion_source_allowed",
        "documents",
        "ingestion_source IS NULL OR ingestion_source IN ('upload', 'connector')",
    )

    # -----------------------------------------------------------------------
    # 3. connector_external_item_id: FK to external_items for connector-ingested docs.
    # -----------------------------------------------------------------------
    op.add_column(
        "documents",
        sa.Column(
            "connector_external_item_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_documents_connector_external_item",
        "documents",
        "external_items",
        ["connector_external_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_documents_connector_external_item",
        "documents",
        ["connector_external_item_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_documents_connector_external_item", table_name="documents")
    op.drop_constraint(
        "fk_documents_connector_external_item", "documents", type_="foreignkey"
    )
    op.drop_column("documents", "connector_external_item_id")
    op.drop_constraint("documents_ingestion_source_allowed", "documents", type_="check")
    op.drop_column("documents", "ingestion_source")

    # Restore the original status constraint (without F245 statuses).
    op.drop_constraint("documents_status_allowed", "documents", type_="check")
    op.create_check_constraint(
        "documents_status_allowed",
        "documents",
        "status IN ("
        "'uploaded', 'processing', 'indexed', 'failed', 'quarantined', 'blocked', "
        "'delete_requested', 'deleting', 'deleted', 'retained_by_policy'"
        ")",
    )
