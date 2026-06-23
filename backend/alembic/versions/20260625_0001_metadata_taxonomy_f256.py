"""smart tags, custom metadata and taxonomy management (F256)

Revision ID: 20260625_0001
Revises: 20260624_0003
Create Date: 2026-06-25

Adds:
  - metadata_fields    — org-defined schema (type, allowed values, required flag)
  - document_metadata  — per-document field values, one row per (document, field)
  - metadata_audit_log — immutable audit trail for every value change
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_0001"
down_revision: str | None = "20260624_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metadata_fields",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("field_type", sa.String(32), nullable=False),
        sa.Column("allowed_values", sa.JSON(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_filterable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", "name", name="uq_metadata_fields_org_name"),
        sa.CheckConstraint(
            "field_type IN ('text', 'select', 'multi_select', 'date', 'boolean', 'number')",
            name="metadata_fields_type_allowed",
        ),
    )
    op.create_index("idx_metadata_fields_org", "metadata_fields", ["organization_id", "is_active"])

    op.create_table(
        "document_metadata",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("field_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["metadata_fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "field_id", name="uq_document_metadata_doc_field"),
    )
    op.create_index("idx_document_metadata_doc", "document_metadata", ["document_id"])
    op.create_index("idx_document_metadata_field", "document_metadata", ["field_id"])
    op.create_index("idx_document_metadata_org", "document_metadata", ["organization_id"])

    op.create_table(
        "metadata_audit_log",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("field_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("changed_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("action", sa.String(32), nullable=False, server_default="set"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["metadata_fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "action IN ('set', 'delete', 'bulk_set')",
            name="metadata_audit_action_allowed",
        ),
    )
    op.create_index("idx_metadata_audit_doc", "metadata_audit_log", ["document_id"])
    op.create_index("idx_metadata_audit_field", "metadata_audit_log", ["field_id"])
    op.create_index(
        "idx_metadata_audit_org_created", "metadata_audit_log", ["organization_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_metadata_audit_org_created", table_name="metadata_audit_log")
    op.drop_index("idx_metadata_audit_field", table_name="metadata_audit_log")
    op.drop_index("idx_metadata_audit_doc", table_name="metadata_audit_log")
    op.drop_table("metadata_audit_log")

    op.drop_index("idx_document_metadata_org", table_name="document_metadata")
    op.drop_index("idx_document_metadata_field", table_name="document_metadata")
    op.drop_index("idx_document_metadata_doc", table_name="document_metadata")
    op.drop_table("document_metadata")

    op.drop_index("idx_metadata_fields_org", table_name="metadata_fields")
    op.drop_table("metadata_fields")
