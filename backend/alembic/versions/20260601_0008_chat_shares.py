"""chat share links

Revision ID: 20260601_0008
Revises: 20260601_0007
Create Date: 2026-06-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260601_0008"
down_revision: str | None = "20260601_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_shares",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chat_session_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("shared_by_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(86), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_shares_chat_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_chat_shares_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shared_by_user_id"],
            ["users.id"],
            name=op.f("fk_chat_shares_shared_by_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_shares")),
        sa.UniqueConstraint("token", name=op.f("uq_chat_shares_token")),
    )
    op.create_index("idx_chat_shares_token", "chat_shares", ["token"], unique=True)
    op.create_index("idx_chat_shares_session", "chat_shares", ["chat_session_id"])


def downgrade() -> None:
    op.drop_index("idx_chat_shares_session", table_name="chat_shares")
    op.drop_index("idx_chat_shares_token", table_name="chat_shares")
    op.drop_table("chat_shares")
