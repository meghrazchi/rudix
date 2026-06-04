"""RAG profile and retrieval preset management

Revision ID: 20260605_0001
Revises: 20260604_0004
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0001"
down_revision: str | None = "20260604_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_profiles",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
            name="fk_rag_profiles_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_rag_profiles_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_rag_profiles_updated_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rag_profiles"),
    )
    op.create_index(
        "idx_rag_profiles_organization_id",
        "rag_profiles",
        ["organization_id"],
    )
    op.create_index(
        "idx_rag_profiles_org_default",
        "rag_profiles",
        ["organization_id", "is_default"],
    )

    op.create_table(
        "rag_profile_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rag_profile_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "config_snapshot",
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
        sa.ForeignKeyConstraint(
            ["rag_profile_id"],
            ["rag_profiles.id"],
            name="fk_rag_profile_versions_rag_profile_id_rag_profiles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name="fk_rag_profile_versions_changed_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rag_profile_versions"),
        sa.UniqueConstraint(
            "rag_profile_id",
            "version_number",
            name="uq_rag_profile_versions_profile_version",
        ),
    )
    op.create_index(
        "idx_rag_profile_versions_profile_id",
        "rag_profile_versions",
        ["rag_profile_id"],
    )

    op.create_table(
        "rag_profile_collection_overrides",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rag_profile_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_rag_profile_collection_overrides_organization_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name="fk_rag_profile_collection_overrides_collection_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rag_profile_id"],
            ["rag_profiles.id"],
            name="fk_rag_profile_collection_overrides_rag_profile_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_rag_profile_collection_overrides_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rag_profile_collection_overrides"),
        sa.UniqueConstraint(
            "organization_id",
            "collection_id",
            name="uq_rag_profile_collection_overrides_org_collection",
        ),
    )
    op.create_index(
        "idx_rag_profile_collection_overrides_org",
        "rag_profile_collection_overrides",
        ["organization_id", "collection_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_rag_profile_collection_overrides_org",
        table_name="rag_profile_collection_overrides",
    )
    op.drop_table("rag_profile_collection_overrides")

    op.drop_index(
        "idx_rag_profile_versions_profile_id",
        table_name="rag_profile_versions",
    )
    op.drop_table("rag_profile_versions")

    op.drop_index("idx_rag_profiles_org_default", table_name="rag_profiles")
    op.drop_index("idx_rag_profiles_organization_id", table_name="rag_profiles")
    op.drop_table("rag_profiles")
