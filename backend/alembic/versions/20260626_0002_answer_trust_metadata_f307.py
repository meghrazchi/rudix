"""Answer evidence contract and trust metadata API (F307)

Revision ID: 20260626_0002
Revises: 20260626_0001
Create Date: 2026-06-26

Adds:
  - chat_messages.trust_metadata_json — JSONB snapshot of the versioned
    AnswerTrustMetadataResponse captured at generation time. NULL for messages
    created before this migration. Enables GET /chat/messages/{id}/trust-metadata
    to serve trust panel data for saved conversations without recomputing it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260626_0002"
down_revision: str | None = "20260626_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("trust_metadata_json", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "trust_metadata_json")
