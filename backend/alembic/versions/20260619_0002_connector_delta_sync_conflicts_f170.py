"""connector delta sync conflicts f170

Revision ID: 20260619_0002
Revises: 20260619_0001
Create Date: 2026-06-19

Adds connector_sync_conflicts table for F170 — Delta sync and conflict handling.
One row per detected conflict on an ExternalItem, tracking:
  - conflict_type: what kind of discrepancy was found (acl_changed, renamed,
    moved, permission_revoked)
  - status: open / resolved / dismissed
  - conflict_detail_json: provider-side snapshot at detection time
  - resolution metadata (who resolved it, when, which strategy)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260619_0002"
down_revision = "20260619_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_sync_conflicts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_item_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("sync_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("provider_item_id", sa.String(1024), nullable=False),
        sa.Column("conflict_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column(
            "conflict_detail",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("resolved_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_strategy", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "conflict_type IN ('acl_changed', 'renamed', 'moved', 'permission_revoked')",
            name="connector_sync_conflicts_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name="connector_sync_conflicts_status_allowed",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_item_id"],
            ["external_items.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["connector_sync_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_connector_sync_conflicts_org_conn_status",
        "connector_sync_conflicts",
        ["organization_id", "connection_id", "status"],
    )
    op.create_index(
        "idx_connector_sync_conflicts_external_item",
        "connector_sync_conflicts",
        ["external_item_id"],
    )
    op.create_index(
        "idx_connector_sync_conflicts_created",
        "connector_sync_conflicts",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_connector_sync_conflicts_created",
        table_name="connector_sync_conflicts",
    )
    op.drop_index(
        "idx_connector_sync_conflicts_external_item",
        table_name="connector_sync_conflicts",
    )
    op.drop_index(
        "idx_connector_sync_conflicts_org_conn_status",
        table_name="connector_sync_conflicts",
    )
    op.drop_table("connector_sync_conflicts")
