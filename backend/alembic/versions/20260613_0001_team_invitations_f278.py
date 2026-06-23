"""team_invitations_f278

Revision ID: 20260613_0001
Revises: 20260612_0002
Create Date: 2026-06-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260613_0001"
down_revision: str | None = "20260612_0002"


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("resend_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("member_id", sa.Uuid(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["member_id"], ["organization_members.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_org_invitations_token_hash"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'expired', 'revoked')",
            name="org_invitations_status_allowed",
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'member', 'viewer', 'reviewer', 'security_admin', 'billing_admin', 'developer')",
            name="org_invitations_role_allowed",
        ),
    )
    op.create_index(
        "idx_org_invitations_org_status", "organization_invitations", ["organization_id", "status"]
    )
    op.create_index(
        "idx_org_invitations_email_org", "organization_invitations", ["email", "organization_id"]
    )
    op.create_index("idx_org_invitations_token_hash", "organization_invitations", ["token_hash"])
    op.create_index("idx_org_invitations_expires", "organization_invitations", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_org_invitations_expires", table_name="organization_invitations")
    op.drop_index("idx_org_invitations_token_hash", table_name="organization_invitations")
    op.drop_index("idx_org_invitations_email_org", table_name="organization_invitations")
    op.drop_index("idx_org_invitations_org_status", table_name="organization_invitations")
    op.drop_table("organization_invitations")
