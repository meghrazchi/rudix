"""bot_delivery_credentials_f261: encrypted platform bot tokens

Revision ID: 20260615_0003
Revises: 20260615_0002
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260615_0003"
down_revision: str | None = "20260615_0002"


def upgrade() -> None:
    op.add_column(
        "bot_installations",
        sa.Column("encrypted_bot_token", sa.Text(), nullable=True),
    )
    op.add_column(
        "bot_installations",
        sa.Column("bot_token_key_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "bot_installations",
        sa.Column("bot_token_algorithm", sa.String(64), nullable=True),
    )
    op.add_column(
        "bot_installations",
        sa.Column("bot_token_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "bot_installations",
        sa.Column("bot_token_scopes", JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "bot_installations",
        sa.Column("bot_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "bot_installations_token_fingerprint_length",
        "bot_installations",
        "bot_token_fingerprint IS NULL OR length(bot_token_fingerprint) = 64",
    )


def downgrade() -> None:
    op.drop_constraint(
        "bot_installations_token_fingerprint_length",
        "bot_installations",
        type_="check",
    )
    op.drop_column("bot_installations", "bot_token_expires_at")
    op.drop_column("bot_installations", "bot_token_scopes")
    op.drop_column("bot_installations", "bot_token_fingerprint")
    op.drop_column("bot_installations", "bot_token_algorithm")
    op.drop_column("bot_installations", "bot_token_key_id")
    op.drop_column("bot_installations", "encrypted_bot_token")
