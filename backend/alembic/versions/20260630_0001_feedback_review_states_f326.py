"""feedback review states and compatibility aliases for F326.

Revision ID: 20260630_0001
Revises: 20260628_0001
Create Date: 2026-06-30

Expands the feedback review queue status constraint to allow the new canonical
review states while keeping legacy aliases valid during rollout.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260630_0001"
down_revision: str | None = "20260628_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_STATUSES = (
    "new",
    "triaged",
    "accepted",
    "rejected",
    "needs_document_update",
    "needs_prompt_retrieval_fix",
    "converted_to_evaluation",
    "resolved",
    "needs_document",
    "eval_created",
    "fixed",
    "duplicate",
)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_feedback_review_items_status_allowed"),
        "feedback_review_items",
        type_="check",
    )
    statuses_sql = ", ".join(repr(status) for status in _STATUSES)
    op.create_check_constraint(
        op.f("ck_feedback_review_items_status_allowed"),
        "feedback_review_items",
        f"status IN ({statuses_sql})",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_feedback_review_items_status_allowed"),
        "feedback_review_items",
        type_="check",
    )
    statuses_sql = ", ".join(
        repr(status)
        for status in (
            "new",
            "triaged",
            "needs_document",
            "accepted",
            "eval_created",
            "fixed",
            "rejected",
            "duplicate",
        )
    )
    op.create_check_constraint(
        op.f("ck_feedback_review_items_status_allowed"),
        "feedback_review_items",
        f"status IN ({statuses_sql})",
    )
