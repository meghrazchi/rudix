"""collection access policies

Revision ID: 20260531_0005
Revises: 20260531_0004
Create Date: 2026-05-31 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0005"
down_revision: str | None = "20260531_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old access_policy check constraint by its exact DB name.
    # We use raw SQL here because op.drop_constraint() would re-apply the
    # naming convention (ck_%(table)s_%(name)s) and double-prefix the name.
    op.execute(
        "ALTER TABLE collections "
        "DROP CONSTRAINT ck_collections_collections_access_policy_allowed"
    )

    # Migrate existing 'restricted' rows to 'admin_only' (safest default)
    op.execute(
        "UPDATE collections SET access_policy = 'admin_only' WHERE access_policy = 'restricted'"
    )

    # Re-create constraint with the extended set of allowed values.
    # Pass the short suffix; the naming convention produces the same full name.
    op.create_check_constraint(
        "collections_access_policy_allowed",
        "collections",
        "access_policy IN ('org_wide', 'admin_only', 'selected_roles', 'selected_members')",
    )

    # Create collection_access_grants table
    op.create_table(
        "collection_access_grants",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("grantee_type", sa.String(32), nullable=False),
        sa.Column("grantee_value", sa.String(255), nullable=False),
        sa.Column("granted_by_id", sa.Uuid(as_uuid=True), nullable=True),
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
            "grantee_type IN ('role', 'member')",
            name="collection_access_grants_grantee_type_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_collection_access_grants_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_id"],
            ["users.id"],
            name=op.f("fk_collection_access_grants_granted_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collection_access_grants")),
        sa.UniqueConstraint(
            "collection_id",
            "grantee_type",
            "grantee_value",
            name="uq_collection_access_grants",
        ),
    )
    op.create_index(
        "idx_collection_access_grants_collection_id",
        "collection_access_grants",
        ["collection_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_collection_access_grants_collection_id",
        table_name="collection_access_grants",
    )
    op.drop_table("collection_access_grants")

    # Drop the extended constraint by raw SQL (same double-prefix issue)
    op.execute(
        "ALTER TABLE collections "
        "DROP CONSTRAINT ck_collections_collections_access_policy_allowed"
    )

    # Revert non-org_wide policies back to 'restricted'
    op.execute(
        "UPDATE collections SET access_policy = 'restricted'"
        " WHERE access_policy IN ('admin_only', 'selected_roles', 'selected_members')"
    )

    # Restore the original two-value constraint
    op.create_check_constraint(
        "collections_access_policy_allowed",
        "collections",
        "access_policy IN ('org_wide', 'restricted')",
    )
