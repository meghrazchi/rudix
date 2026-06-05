"""Prompt template management and versioning

Revision ID: 20260605_0002
Revises: 20260605_0001
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0002"
down_revision: str | None = "20260605_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("latest_version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_version_number", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(as_uuid=True), nullable=True),
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
            ["organization_id"],
            ["organizations.id"],
            name="fk_prompt_templates_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_prompt_templates_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_prompt_templates_updated_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_templates"),
        sa.UniqueConstraint(
            "organization_id",
            "template_key",
            name="uq_prompt_templates_org_key",
        ),
    )
    op.create_index(
        "idx_prompt_templates_organization_id",
        "prompt_templates",
        ["organization_id"],
    )
    op.create_index(
        "idx_prompt_templates_org_key",
        "prompt_templates",
        ["organization_id", "template_key"],
    )

    op.create_table(
        "prompt_template_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("prompt_template_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "variable_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "preview_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("change_note", sa.String(length=1000), nullable=True),
        sa.Column("source_version_number", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("reviewed_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("published_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "state IN ('draft', 'review', 'published')",
            name="prompt_template_versions_state_allowed",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="prompt_template_versions_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id"],
            ["prompt_templates.id"],
            name="fk_prompt_template_versions_prompt_template_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_prompt_template_versions_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name="fk_prompt_template_versions_reviewed_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"],
            ["users.id"],
            name="fk_prompt_template_versions_published_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_template_versions"),
        sa.UniqueConstraint(
            "prompt_template_id",
            "version_number",
            name="uq_prompt_template_versions_template_version",
        ),
    )
    op.create_index(
        "idx_prompt_template_versions_template_id",
        "prompt_template_versions",
        ["prompt_template_id"],
    )
    op.create_index(
        "idx_prompt_template_versions_state",
        "prompt_template_versions",
        ["prompt_template_id", "state"],
    )

    op.add_column(
        "chat_messages",
        sa.Column("prompt_template_version_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_messages_prompt_tmpl_version_id",
        "chat_messages",
        "prompt_template_versions",
        ["prompt_template_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_chat_messages_prompt_template_version",
        "chat_messages",
        ["prompt_template_version_id"],
    )

    op.add_column(
        "evaluation_runs",
        sa.Column("prompt_template_version_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_evaluation_runs_prompt_tmpl_version_id",
        "evaluation_runs",
        "prompt_template_versions",
        ["prompt_template_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_evaluation_runs_prompt_template_version",
        "evaluation_runs",
        ["prompt_template_version_id"],
    )

    op.add_column(
        "agent_runs",
        sa.Column("prompt_template_version_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_prompt_tmpl_version_id",
        "agent_runs",
        "prompt_template_versions",
        ["prompt_template_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_agent_runs_prompt_template_version",
        "agent_runs",
        ["prompt_template_version_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_runs_prompt_template_version", table_name="agent_runs")
    op.drop_constraint(
        "fk_agent_runs_prompt_tmpl_version_id",
        "agent_runs",
        type_="foreignkey",
    )
    op.drop_column("agent_runs", "prompt_template_version_id")

    op.drop_index(
        "idx_evaluation_runs_prompt_template_version",
        table_name="evaluation_runs",
    )
    op.drop_constraint(
        "fk_evaluation_runs_prompt_tmpl_version_id",
        "evaluation_runs",
        type_="foreignkey",
    )
    op.drop_column("evaluation_runs", "prompt_template_version_id")

    op.drop_index(
        "idx_chat_messages_prompt_template_version",
        table_name="chat_messages",
    )
    op.drop_constraint(
        "fk_chat_messages_prompt_tmpl_version_id",
        "chat_messages",
        type_="foreignkey",
    )
    op.drop_column("chat_messages", "prompt_template_version_id")

    op.drop_index(
        "idx_prompt_template_versions_state",
        table_name="prompt_template_versions",
    )
    op.drop_index(
        "idx_prompt_template_versions_template_id",
        table_name="prompt_template_versions",
    )
    op.drop_table("prompt_template_versions")

    op.drop_index("idx_prompt_templates_org_key", table_name="prompt_templates")
    op.drop_index(
        "idx_prompt_templates_organization_id",
        table_name="prompt_templates",
    )
    op.drop_table("prompt_templates")
