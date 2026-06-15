"""hybrid retrieval: text_search_vector tsvector on document_chunks (F293)

Revision ID: 20260615_0006
Revises: 20260615_0005
Create Date: 2026-06-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260615_0006"
down_revision: str | None = "20260615_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE document_chunks "
            "ADD COLUMN text_search_vector tsvector "
            "GENERATED ALWAYS AS (to_tsvector('english', COALESCE(text, ''))) STORED"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX idx_chunks_text_search ON document_chunks USING GIN (text_search_vector)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_chunks_text_search"))
    op.execute(sa.text("ALTER TABLE document_chunks DROP COLUMN IF EXISTS text_search_vector"))
