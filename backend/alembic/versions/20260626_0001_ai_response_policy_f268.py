"""AI response policy engine (F268)

Revision ID: 20260626_0001
Revises: 20260625_0002
Create Date: 2026-06-26

Adds:
  - org_ai_response_policies — per-org citation, confidence, topic, and disclaimer rules
  - collection_ai_response_policy_overrides — per-collection overrides on top of org policy
  - policy_evaluation_logs — audit trail of every policy decision made during chat
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_0001"
down_revision: str | None = "20260625_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_ai_response_policies",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("policy_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        # Citation rules
        sa.Column("citation_mode", sa.String(32), nullable=False, server_default="recommended"),
        # Confidence threshold
        sa.Column("min_confidence_threshold", sa.Float(), nullable=True),
        sa.Column("no_answer_behavior", sa.String(32), nullable=False, server_default="warn"),
        # Source freshness
        sa.Column("stale_source_behavior", sa.String(32), nullable=False, server_default="warn"),
        # Topic controls
        sa.Column("blocked_topics", sa.JSON(), nullable=True),
        sa.Column("allowed_topics", sa.JSON(), nullable=True),
        # Source quantity gate
        sa.Column("min_sources_required", sa.Integer(), nullable=True),
        # Disclaimer injection
        sa.Column("disclaimer_text", sa.Text(), nullable=True),
        sa.Column("disclaimer_position", sa.String(16), nullable=False, server_default="prepend"),
        # Custom refusal message
        sa.Column("refusal_message", sa.Text(), nullable=True),
        # Timestamps
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "citation_mode IN ('required', 'recommended', 'disabled')",
            name="org_ai_policy_citation_mode_allowed",
        ),
        sa.CheckConstraint(
            "no_answer_behavior IN ('refuse', 'warn', 'allow')",
            name="org_ai_policy_no_answer_behavior_allowed",
        ),
        sa.CheckConstraint(
            "stale_source_behavior IN ('warn', 'refuse', 'ignore')",
            name="org_ai_policy_stale_source_behavior_allowed",
        ),
        sa.CheckConstraint(
            "disclaimer_position IN ('prepend', 'append')",
            name="org_ai_policy_disclaimer_position_allowed",
        ),
        sa.CheckConstraint(
            "min_confidence_threshold IS NULL OR (min_confidence_threshold >= 0.0 AND min_confidence_threshold <= 1.0)",
            name="org_ai_policy_confidence_threshold_range",
        ),
        sa.CheckConstraint(
            "min_sources_required IS NULL OR min_sources_required >= 0",
            name="org_ai_policy_min_sources_non_negative",
        ),
    )
    op.create_index(
        "idx_org_ai_policy_org_active",
        "org_ai_response_policies",
        ["organization_id", "is_active"],
    )

    op.create_table(
        "collection_ai_response_policy_overrides",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("org_policy_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(as_uuid=True), nullable=True),
        # All fields nullable — NULL means inherit from org policy
        sa.Column("citation_mode", sa.String(32), nullable=True),
        sa.Column("min_confidence_threshold", sa.Float(), nullable=True),
        sa.Column("no_answer_behavior", sa.String(32), nullable=True),
        sa.Column("stale_source_behavior", sa.String(32), nullable=True),
        sa.Column("blocked_topics", sa.JSON(), nullable=True),
        sa.Column("allowed_topics", sa.JSON(), nullable=True),
        sa.Column("min_sources_required", sa.Integer(), nullable=True),
        sa.Column("disclaimer_text", sa.Text(), nullable=True),
        sa.Column("refusal_message", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_policy_id"],
            ["org_ai_response_policies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "org_policy_id",
            "collection_id",
            name="uq_collection_ai_policy_org_collection",
        ),
        sa.CheckConstraint(
            "citation_mode IS NULL OR citation_mode IN ('required', 'recommended', 'disabled')",
            name="col_ai_policy_citation_mode_allowed",
        ),
        sa.CheckConstraint(
            "no_answer_behavior IS NULL OR no_answer_behavior IN ('refuse', 'warn', 'allow')",
            name="col_ai_policy_no_answer_behavior_allowed",
        ),
        sa.CheckConstraint(
            "stale_source_behavior IS NULL OR stale_source_behavior IN ('warn', 'refuse', 'ignore')",
            name="col_ai_policy_stale_source_behavior_allowed",
        ),
        sa.CheckConstraint(
            "min_confidence_threshold IS NULL OR (min_confidence_threshold >= 0.0 AND min_confidence_threshold <= 1.0)",
            name="col_ai_policy_confidence_threshold_range",
        ),
    )
    op.create_index(
        "idx_col_ai_policy_org",
        "collection_ai_response_policy_overrides",
        ["org_policy_id"],
    )
    op.create_index(
        "idx_col_ai_policy_collection",
        "collection_ai_response_policy_overrides",
        ["collection_id"],
    )

    op.create_table(
        "policy_evaluation_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("org_policy_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("chat_session_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("chat_message_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="allowed"),
        sa.Column("policy_source", sa.String(16), nullable=False, server_default="none"),
        sa.Column("violated_rules", sa.JSON(), nullable=True),
        sa.Column("warning_flags", sa.JSON(), nullable=True),
        sa.Column("question_preview", sa.String(256), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("citation_count", sa.Integer(), nullable=True),
        sa.Column("stale_source_count", sa.Integer(), nullable=True),
        sa.Column("is_preview_run", sa.Boolean(), nullable=False, server_default="false"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["org_policy_id"], ["org_ai_response_policies.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "outcome IN ('allowed', 'blocked', 'warned')",
            name="policy_eval_log_outcome_allowed",
        ),
        sa.CheckConstraint(
            "policy_source IN ('org', 'collection', 'none')",
            name="policy_eval_log_source_allowed",
        ),
    )
    op.create_index(
        "idx_policy_eval_log_org_created",
        "policy_evaluation_logs",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "idx_policy_eval_log_org_outcome",
        "policy_evaluation_logs",
        ["organization_id", "outcome"],
    )
    op.create_index(
        "idx_policy_eval_log_policy",
        "policy_evaluation_logs",
        ["org_policy_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_policy_eval_log_policy", table_name="policy_evaluation_logs")
    op.drop_index("idx_policy_eval_log_org_outcome", table_name="policy_evaluation_logs")
    op.drop_index("idx_policy_eval_log_org_created", table_name="policy_evaluation_logs")
    op.drop_table("policy_evaluation_logs")

    op.drop_index(
        "idx_col_ai_policy_collection",
        table_name="collection_ai_response_policy_overrides",
    )
    op.drop_index(
        "idx_col_ai_policy_org",
        table_name="collection_ai_response_policy_overrides",
    )
    op.drop_table("collection_ai_response_policy_overrides")

    op.drop_index("idx_org_ai_policy_org_active", table_name="org_ai_response_policies")
    op.drop_table("org_ai_response_policies")
