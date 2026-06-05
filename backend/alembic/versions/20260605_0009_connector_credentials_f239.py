"""connector credential vault

Revision ID: 20260605_0009
Revises: 20260605_0008
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260605_0009"
down_revision: str | None = "20260605_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_credentials",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("auth_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("encryption_key_id", sa.String(128), nullable=False),
        sa.Column("encryption_algorithm", sa.String(64), nullable=False),
        sa.Column("secret_fingerprint", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            "auth_type IN ('oauth2', 'api_token', 'service_account', 'basic')",
            name="connector_credentials_auth_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'expired', 'revoked', 'error')",
            name="connector_credentials_status_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="connector_credentials_version_positive"),
        sa.CheckConstraint(
            "length(trim(encryption_key_id)) >= 1",
            name="connector_credentials_key_id_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(encryption_algorithm)) >= 1",
            name="connector_credentials_algorithm_not_blank",
        ),
        sa.CheckConstraint(
            "length(secret_fingerprint) = 64",
            name="connector_credentials_fingerprint_length",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_connector_credentials_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            name=op.f("fk_connector_credentials_connection_id_connector_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_credentials")),
        sa.UniqueConstraint(
            "connection_id",
            "version",
            name="uq_connector_credentials_connection_version",
        ),
    )
    op.create_index(
        "idx_connector_credentials_org_connection",
        "connector_credentials",
        ["organization_id", "connection_id"],
    )
    op.create_index(
        "idx_connector_credentials_current",
        "connector_credentials",
        ["connection_id", "is_current"],
    )
    op.create_index(
        "idx_connector_credentials_status_expires",
        "connector_credentials",
        ["status", "expires_at"],
    )

    op.create_table(
        "connector_oauth_states",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("external_account_id", sa.String(512), nullable=True),
        sa.Column("requested_scopes", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(255), nullable=True),
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
            "length(state_hash) = 64",
            name="connector_oauth_states_state_hash_length",
        ),
        sa.CheckConstraint(
            "connection_id IS NULL OR organization_id IS NOT NULL",
            name="connector_oauth_states_connection_has_org",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_connector_oauth_states_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_connector_oauth_states_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            name=op.f("fk_connector_oauth_states_connection_id_connector_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_connector_oauth_states_collection_id_collections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_oauth_states")),
        sa.UniqueConstraint("state_hash", name="uq_connector_oauth_states_state_hash"),
    )
    op.create_index(
        "idx_connector_oauth_states_org_provider",
        "connector_oauth_states",
        ["organization_id", "provider_key"],
    )
    op.create_index(
        "idx_connector_oauth_states_connection",
        "connector_oauth_states",
        ["connection_id"],
    )
    op.create_index(
        "idx_connector_oauth_states_expires",
        "connector_oauth_states",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_connector_oauth_states_expires", table_name="connector_oauth_states")
    op.drop_index("idx_connector_oauth_states_connection", table_name="connector_oauth_states")
    op.drop_index("idx_connector_oauth_states_org_provider", table_name="connector_oauth_states")
    op.drop_table("connector_oauth_states")

    op.drop_index("idx_connector_credentials_status_expires", table_name="connector_credentials")
    op.drop_index("idx_connector_credentials_current", table_name="connector_credentials")
    op.drop_index("idx_connector_credentials_org_connection", table_name="connector_credentials")
    op.drop_table("connector_credentials")
