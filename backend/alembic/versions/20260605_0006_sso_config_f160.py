"""Enterprise SSO/SAML config

Revision ID: 20260605_0006
Revises: 20260605_0005
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260605_0006"
down_revision: str | None = "20260605_0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_sso_configs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sso_type", sa.String(length=16), nullable=False, server_default="saml"),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("idp_metadata_url", sa.String(length=2048), nullable=True),
        sa.Column("idp_metadata_xml", sa.Text(), nullable=True),
        sa.Column("idp_sso_url", sa.String(length=2048), nullable=True),
        sa.Column("idp_entity_id", sa.String(length=1024), nullable=True),
        sa.Column("idp_certificate", sa.Text(), nullable=True),
        sa.Column("sp_entity_id", sa.String(length=2048), nullable=False),
        sa.Column("sp_acs_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "attribute_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_result", sa.String(length=16), nullable=True),
        sa.Column("last_test_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "sso_type IN ('saml', 'oidc')",
            name="ck_org_sso_configs_sso_type",
        ),
        sa.CheckConstraint(
            "last_test_result IS NULL OR last_test_result IN ('success', 'failure')",
            name="ck_org_sso_configs_last_test_result",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_org_sso_configs_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_org_sso_configs_created_by_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_org_sso_configs_updated_by_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_sso_configs"),
        sa.UniqueConstraint("organization_id", name="uq_org_sso_configs_org_id"),
    )
    op.create_index("idx_org_sso_configs_org_id", "org_sso_configs", ["organization_id"])
    op.create_index("idx_org_sso_configs_domain", "org_sso_configs", ["domain"])


def downgrade() -> None:
    op.drop_index("idx_org_sso_configs_domain", table_name="org_sso_configs")
    op.drop_index("idx_org_sso_configs_org_id", table_name="org_sso_configs")
    op.drop_table("org_sso_configs")
