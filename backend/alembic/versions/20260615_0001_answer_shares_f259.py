"""answer share links (F259)

Revision ID: 20260615_0001
Revises: 20260614_0001
Create Date: 2026-06-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260615_0001"
down_revision: str | None = "20260614_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_shares",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chat_message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("shared_by_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(86), nullable=False),
        sa.Column("access_mode", sa.String(32), nullable=False, server_default="org_only"),
        sa.Column("allowed_user_ids", sa.JSON(), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
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
            ["chat_message_id"],
            ["chat_messages.id"],
            name=op.f("fk_answer_shares_chat_message_id_chat_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_answer_shares_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shared_by_user_id"],
            ["users.id"],
            name=op.f("fk_answer_shares_shared_by_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_answer_shares")),
        sa.UniqueConstraint("token", name=op.f("uq_answer_shares_token")),
    )
    op.create_index("idx_answer_shares_token", "answer_shares", ["token"], unique=True)
    op.create_index("idx_answer_shares_message", "answer_shares", ["chat_message_id"])
    op.create_index("idx_answer_shares_org", "answer_shares", ["organization_id"])


def downgrade() -> None:
    op.drop_index("idx_answer_shares_org", table_name="answer_shares")
    op.drop_index("idx_answer_shares_message", table_name="answer_shares")
    op.drop_index("idx_answer_shares_token", table_name="answer_shares")
    op.drop_table("answer_shares")
