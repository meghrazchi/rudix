"""connector permission review f169

Revision ID: 20260619_0001
Revises: 20260618_0001
Create Date: 2026-06-19

Adds connector_permission_reviews table for F169 — Connector permission review.
One row per connector connection, tracking:
  - the permission snapshot captured at review time
  - detected scope warnings (broad access, admin scopes, etc.)
  - explicit admin confirmation before first sync
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260619_0001"
down_revision = "20260618_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_permission_reviews",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "permission_snapshot",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "scope_warnings",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("is_broad_scope", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default="false"),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("connection_id", name="uq_connector_permission_reviews_connection"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_connector_permission_reviews_org",
        "connector_permission_reviews",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_connector_permission_reviews_org",
        table_name="connector_permission_reviews",
    )
    op.drop_table("connector_permission_reviews")
