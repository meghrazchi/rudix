"""service accounts and machine users (F264)

Revision ID: 20260622_0002
Revises: 20260622_0001
Create Date: 2026-06-22

Adds:
  - service_accounts table — non-human identities for automation, CI, SDKs, etc.
  - service_account_tokens table — scoped bearer tokens (svc_ prefix, stored hashed)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260622_0002"
down_revision: str | None = "20260622_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("environment", sa.String(32), nullable=False, server_default="production"),
        sa.Column("scopes", sa.dialects.postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("idx_service_accounts_org_id", "service_accounts", ["organization_id"])

    op.create_table(
        "service_account_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "service_account_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("service_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("token_prefix", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(64), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("token_hash", name="uq_service_account_tokens_token_hash"),
    )
    op.create_index(
        "idx_service_account_tokens_account_id", "service_account_tokens", ["service_account_id"]
    )
    op.create_index(
        "idx_service_account_tokens_token_hash", "service_account_tokens", ["token_hash"]
    )
    op.create_index(
        "idx_service_account_tokens_org_id", "service_account_tokens", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_service_account_tokens_org_id", table_name="service_account_tokens")
    op.drop_index("idx_service_account_tokens_token_hash", table_name="service_account_tokens")
    op.drop_index("idx_service_account_tokens_account_id", table_name="service_account_tokens")
    op.drop_table("service_account_tokens")
    op.drop_index("idx_service_accounts_org_id", table_name="service_accounts")
    op.drop_table("service_accounts")
