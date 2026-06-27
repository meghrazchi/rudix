"""org_workflows and user_memory_preferences tables for F343.

Revision ID: 20260630_0003
Revises: 20260630_0002
Create Date: 2026-06-27

Stores org-scoped reusable workflow templates and per-user RAG default
preferences.  No sensitive source text is persisted — steps hold only
labels, query templates, and collection UUIDs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260630_0003"
down_revision: str | None = "20260630_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_WORKFLOW_TYPES = (
    "audit_evidence_pack",
    "policy_comparison",
    "contract_review",
    "onboarding_faq",
    "custom",
)
_SCOPE_VALUES = ("all", "collection", "docs", "none")


def upgrade() -> None:
    op.create_table(
        "org_workflows",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("workflow_type", sa.String(64), nullable=False, server_default="custom"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("steps", sa.Text, nullable=True),
        sa.Column("role_scope", sa.String(512), nullable=True),
        sa.Column("collection_scope_ids", sa.Text, nullable=True),
        sa.Column(
            "verified_knowledge_card_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("verified_answers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("use_count", sa.Integer, nullable=False, server_default="0"),
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
            "workflow_type IN ({})".format(", ".join(f"'{t}'" for t in _WORKFLOW_TYPES)),
            name="org_workflows_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="org_workflows_status_allowed",
        ),
    )
    op.create_index(
        "idx_org_workflows_org_status",
        "org_workflows",
        ["organization_id", "status"],
    )
    op.create_index(
        "idx_org_workflows_org_type",
        "org_workflows",
        ["organization_id", "workflow_type"],
    )
    op.create_index(
        "idx_org_workflows_created_by",
        "org_workflows",
        ["created_by_id"],
    )

    op.create_table(
        "user_memory_preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("preferred_scope", sa.String(32), nullable=True),
        sa.Column("preferred_collection_ids", sa.Text, nullable=True),
        sa.Column(
            "rag_profile_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("rag_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("answer_language", sa.String(8), nullable=True),
        sa.Column("extra_defaults", sa.Text, nullable=True),
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
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_user_memory_preferences_org_user",
        ),
        sa.CheckConstraint(
            "preferred_scope IS NULL OR preferred_scope IN ({})".format(
                ", ".join(f"'{s}'" for s in _SCOPE_VALUES)
            ),
            name="user_memory_preferences_scope_allowed",
        ),
    )
    op.create_index(
        "idx_user_memory_preferences_org_user",
        "user_memory_preferences",
        ["organization_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_memory_preferences_org_user", "user_memory_preferences")
    op.drop_table("user_memory_preferences")
    op.drop_index("idx_org_workflows_created_by", "org_workflows")
    op.drop_index("idx_org_workflows_org_type", "org_workflows")
    op.drop_index("idx_org_workflows_org_status", "org_workflows")
    op.drop_table("org_workflows")
