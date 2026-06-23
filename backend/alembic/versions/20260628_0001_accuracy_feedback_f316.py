"""Accuracy feedback capture from trust panel (F316).

Revision ID: 20260628_0001
Revises: 20260627_0001
Create Date: 2026-06-28

Adds:
  - message_feedback.trust_metadata_json: redacted trust metadata snapshot
    captured at feedback submission time for debugging.
  - message_feedback.trace_id: request/trace correlation ID from the
    retrieval diagnostics, used for log correlation.
  - message_feedback.selected_citation_ids: list of document IDs the user
    explicitly flagged when reporting an issue from the trust panel.
  - feedback_review_items: drops and recreates the status CHECK constraint
    to add the new 'accepted' state (reviewer accepted for investigation).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260628_0001"
down_revision: str | None = "20260627_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_OLD_STATUSES = ("new", "triaged", "needs_document", "eval_created", "fixed", "rejected", "duplicate")
_NEW_STATUSES = ("new", "triaged", "needs_document", "accepted", "eval_created", "fixed", "rejected", "duplicate")


def upgrade() -> None:
    # Add F316 columns to message_feedback
    op.add_column(
        "message_feedback",
        sa.Column("trust_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "message_feedback",
        sa.Column("trace_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "message_feedback",
        sa.Column("selected_citation_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Drop the old status CHECK constraint and recreate it with 'accepted'
    op.drop_constraint(
        op.f("ck_feedback_review_items_status_allowed"),
        "feedback_review_items",
        type_="check",
    )
    statuses_sql = ", ".join(repr(s) for s in _NEW_STATUSES)
    op.create_check_constraint(
        op.f("ck_feedback_review_items_status_allowed"),
        "feedback_review_items",
        f"status IN ({statuses_sql})",
    )


def downgrade() -> None:
    # Restore old CHECK constraint (rows with 'accepted' status must not exist)
    op.drop_constraint(
        op.f("ck_feedback_review_items_status_allowed"),
        "feedback_review_items",
        type_="check",
    )
    statuses_sql = ", ".join(repr(s) for s in _OLD_STATUSES)
    op.create_check_constraint(
        op.f("ck_feedback_review_items_status_allowed"),
        "feedback_review_items",
        f"status IN ({statuses_sql})",
    )

    op.drop_column("message_feedback", "selected_citation_ids")
    op.drop_column("message_feedback", "trace_id")
    op.drop_column("message_feedback", "trust_metadata_json")
