"""bot_installations_f261: Slack and Teams bot metadata

Revision ID: 20260615_0002
Revises: 20260615_0001
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260615_0002"
down_revision: str | None = "20260615_0001"


def upgrade() -> None:
    op.create_table(
        "bot_installations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("external_workspace_id", sa.String(255), nullable=False),
        sa.Column("external_tenant_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("external_team_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="enabled"),
        sa.Column("default_source_scope", JSONB(), nullable=False, server_default="{}"),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("installed_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "provider IN ('slack', 'teams')",
            name="bot_installations_provider_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('enabled', 'disabled')",
            name="bot_installations_status_allowed",
        ),
        sa.UniqueConstraint(
            "provider",
            "external_workspace_id",
            "external_tenant_id",
            "external_team_id",
            name="uq_bot_installations_external_scope",
        ),
    )
    op.create_index(
        "idx_bot_installations_org_provider",
        "bot_installations",
        ["organization_id", "provider"],
    )
    op.create_index(
        "idx_bot_installations_external",
        "bot_installations",
        ["provider", "external_workspace_id"],
    )

    op.create_table(
        "bot_user_mappings",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("installation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rudix_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("external_email", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installation_id"], ["bot_installations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rudix_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="bot_user_mappings_status_allowed",
        ),
        sa.UniqueConstraint(
            "installation_id",
            "external_user_id",
            name="uq_bot_user_mappings_external_user",
        ),
    )
    op.create_index(
        "idx_bot_user_mappings_org_user",
        "bot_user_mappings",
        ["organization_id", "rudix_user_id"],
    )
    op.create_index(
        "idx_bot_user_mappings_installation",
        "bot_user_mappings",
        ["installation_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_bot_user_mappings_installation", "bot_user_mappings")
    op.drop_index("idx_bot_user_mappings_org_user", "bot_user_mappings")
    op.drop_table("bot_user_mappings")
    op.drop_index("idx_bot_installations_external", "bot_installations")
    op.drop_index("idx_bot_installations_org_provider", "bot_installations")
    op.drop_table("bot_installations")
