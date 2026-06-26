"""activity_timeline_events table for F337 agent activity timeline.

Revision ID: 20260630_0002
Revises: 20260630_0001
Create Date: 2026-06-26

Stores per-step activity events emitted during chat answer generation so the
timeline can be replayed from history and attached to the resulting chat message
once it is persisted.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260630_0002"
down_revision: str | None = "20260630_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_STATES = ("pending", "running", "success", "warning", "failed", "skipped")


def upgrade() -> None:
    op.create_table(
        "activity_timeline_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chat_session_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chat_message_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
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
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            "state IN ({})".format(", ".join(f"'{s}'" for s in _STATES)),
            name="activity_timeline_events_state_allowed",
        ),
    )
    op.create_index(
        "idx_activity_timeline_events_session_seq",
        "activity_timeline_events",
        ["chat_session_id", "sequence"],
    )
    op.create_index(
        "idx_activity_timeline_events_message",
        "activity_timeline_events",
        ["chat_message_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_activity_timeline_events_message", "activity_timeline_events")
    op.drop_index("idx_activity_timeline_events_session_seq", "activity_timeline_events")
    op.drop_table("activity_timeline_events")
