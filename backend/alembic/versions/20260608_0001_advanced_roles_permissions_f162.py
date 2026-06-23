"""Advanced roles and custom permissions (F162)

Revision ID: 20260608_0001
Revises: 20260607_0001
Create Date: 2026-06-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260608_0001"
down_revision: str | None = "20260607_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ── custom_roles ──────────────────────────────────────────────────────────
    op.create_table(
        "custom_roles",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base_role", sa.String(length=32), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_custom_roles_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_custom_roles_created_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_custom_roles"),
        sa.UniqueConstraint("organization_id", "name", name="uq_custom_roles_org_name"),
    )
    op.create_index("idx_custom_roles_org_id", "custom_roles", ["organization_id"])

    # ── custom_role_permissions ───────────────────────────────────────────────
    op.create_table(
        "custom_role_permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("custom_role_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["custom_role_id"],
            ["custom_roles.id"],
            name="fk_custom_role_permissions_role_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_custom_role_permissions"),
        sa.UniqueConstraint(
            "custom_role_id",
            "permission",
            name="uq_custom_role_permissions_role_perm",
        ),
    )
    op.create_index(
        "idx_custom_role_permissions_role_id",
        "custom_role_permissions",
        ["custom_role_id"],
    )

    # ── organization_members: expand role constraint + add custom_role_id ─────
    op.drop_constraint(
        "organization_members_role_allowed",
        "organization_members",
        type_="check",
    )
    op.create_check_constraint(
        "organization_members_role_allowed",
        "organization_members",
        (
            "role IN ("
            "'owner', 'admin', 'member', 'viewer', "
            "'reviewer', 'security_admin', 'billing_admin', 'developer'"
            ")"
        ),
    )
    op.add_column(
        "organization_members",
        sa.Column("custom_role_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_organization_members_custom_role_id",
        "organization_members",
        "custom_roles",
        ["custom_role_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_organization_members_custom_role_id",
        "organization_members",
        ["custom_role_id"],
        postgresql_where=sa.text("custom_role_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_organization_members_custom_role_id",
        table_name="organization_members",
    )
    op.drop_constraint(
        "fk_organization_members_custom_role_id",
        "organization_members",
        type_="foreignkey",
    )
    op.drop_column("organization_members", "custom_role_id")
    op.drop_constraint(
        "organization_members_role_allowed",
        "organization_members",
        type_="check",
    )
    op.create_check_constraint(
        "organization_members_role_allowed",
        "organization_members",
        "role IN ('owner', 'admin', 'member', 'viewer')",
    )

    op.drop_index(
        "idx_custom_role_permissions_role_id",
        table_name="custom_role_permissions",
    )
    op.drop_table("custom_role_permissions")

    op.drop_index("idx_custom_roles_org_id", table_name="custom_roles")
    op.drop_table("custom_roles")
