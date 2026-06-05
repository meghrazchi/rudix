"""Model provider settings and fallback policy

Revision ID: 20260605_0003
Revises: 20260605_0002
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0003"
down_revision: str | None = "20260605_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_model_provider_settings",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("llm_model", sa.String(length=255), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("fallback_model", sa.String(length=255), nullable=True),
        sa.Column(
            "disabled_models",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.CheckConstraint(
            "max_tokens IS NULL OR max_tokens >= 1",
            name="org_model_provider_settings_max_tokens_positive",
        ),
        sa.CheckConstraint(
            "timeout_seconds IS NULL OR timeout_seconds >= 1",
            name="org_model_provider_settings_timeout_positive",
        ),
        sa.CheckConstraint(
            "max_retries IS NULL OR (max_retries >= 0 AND max_retries <= 10)",
            name="org_model_provider_settings_max_retries_range",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="org_model_provider_settings_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_model_provider_settings_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_org_model_provider_settings_updated_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_model_provider_settings"),
        sa.UniqueConstraint(
            "organization_id",
            name="uq_org_model_provider_settings_org",
        ),
    )
    op.create_index(
        "idx_org_model_provider_settings_org_id",
        "org_model_provider_settings",
        ["organization_id"],
    )

    op.create_table(
        "org_model_provider_change_log",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "settings_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("change_note", sa.String(length=1000), nullable=True),
        sa.Column("changed_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="org_model_provider_change_log_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_model_provider_change_log_org_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name="fk_org_model_provider_change_log_changed_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_model_provider_change_log"),
        sa.UniqueConstraint(
            "organization_id",
            "version_number",
            name="uq_org_model_provider_change_log_org_version",
        ),
    )
    op.create_index(
        "idx_org_model_provider_change_log_org_id",
        "org_model_provider_change_log",
        ["organization_id"],
    )
    op.create_index(
        "idx_org_model_provider_change_log_org_version",
        "org_model_provider_change_log",
        ["organization_id", "version_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_org_model_provider_change_log_org_version",
        table_name="org_model_provider_change_log",
    )
    op.drop_index(
        "idx_org_model_provider_change_log_org_id",
        table_name="org_model_provider_change_log",
    )
    op.drop_table("org_model_provider_change_log")

    op.drop_index(
        "idx_org_model_provider_settings_org_id",
        table_name="org_model_provider_settings",
    )
    op.drop_table("org_model_provider_settings")
