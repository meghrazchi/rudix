"""SCIM provisioning and domain verification

Revision ID: 20260605_0007
Revises: 20260605_0006
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0007"
down_revision: str | None = "20260605_0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ── users: add SCIM / lifecycle columns ──────────────────────────────────
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "users",
        sa.Column(
            "provisioned_by",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "users",
        sa.Column("scim_external_id", sa.String(length=1024), nullable=True),
    )
    op.create_index(
        "idx_users_scim_external_id",
        "users",
        ["organization_id", "scim_external_id"],
        unique=True,
        postgresql_where=sa.text("scim_external_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_users_provisioned_by",
        "users",
        "provisioned_by IN ('manual', 'sso', 'scim')",
    )

    # ── org_domain_verifications ──────────────────────────────────────────────
    op.create_table(
        "org_domain_verifications",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("verification_token", sa.String(length=128), nullable=False, unique=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
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
            "status IN ('pending', 'verified', 'failed')",
            name="ck_org_domain_verifications_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_domain_verifications_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_org_domain_verifications_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_domain_verifications"),
        sa.UniqueConstraint(
            "organization_id", "domain", name="uq_org_domain_verifications_org_domain"
        ),
    )
    op.create_index(
        "idx_org_domain_verifications_org_id",
        "org_domain_verifications",
        ["organization_id"],
    )
    op.create_index(
        "idx_org_domain_verifications_token",
        "org_domain_verifications",
        ["verification_token"],
    )

    # ── org_scim_configs ──────────────────────────────────────────────────────
    op.create_table(
        "org_scim_configs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("token_hash", sa.String(length=256), nullable=False),
        sa.Column("token_hint", sa.String(length=8), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("provisioned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deprovisioned_count", sa.Integer(), nullable=False, server_default="0"),
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
            name="fk_org_scim_configs_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_org_scim_configs_created_by_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_org_scim_configs_updated_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_scim_configs"),
        sa.UniqueConstraint("organization_id", name="uq_org_scim_configs_org_id"),
    )
    op.create_index(
        "idx_org_scim_configs_org_id", "org_scim_configs", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_org_scim_configs_org_id", table_name="org_scim_configs")
    op.drop_table("org_scim_configs")

    op.drop_index(
        "idx_org_domain_verifications_token",
        table_name="org_domain_verifications",
    )
    op.drop_index(
        "idx_org_domain_verifications_org_id",
        table_name="org_domain_verifications",
    )
    op.drop_table("org_domain_verifications")

    op.drop_index("idx_users_scim_external_id", table_name="users")
    op.drop_constraint("ck_users_provisioned_by", "users", type_="check")
    op.drop_column("users", "scim_external_id")
    op.drop_column("users", "provisioned_by")
    op.drop_column("users", "is_active")
