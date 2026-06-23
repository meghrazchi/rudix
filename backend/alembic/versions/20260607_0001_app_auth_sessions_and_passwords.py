"""app auth sessions and password fields

Revision ID: 20260607_0001
Revises: 20260606_0001
Create Date: 2026-06-07 00:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260607_0001"
down_revision: str | None = "20260606_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("hashed_password", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("password_state", sa.String(length=32), nullable=False, server_default="unset"),
    )
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("account_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("account_locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "users_password_state_allowed",
        "users",
        "password_state IN ('unset', 'active', 'must_change', 'locked')",
    )

    op.create_table(
        "auth_refresh_sessions",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_token_jti", sa.String(length=64), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
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
            name=op.f("fk_auth_refresh_sessions_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_refresh_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_refresh_sessions")),
        sa.UniqueConstraint(
            "refresh_token_hash", name="uq_auth_refresh_sessions_refresh_token_hash"
        ),
        sa.UniqueConstraint("refresh_token_jti", name="uq_auth_refresh_sessions_refresh_token_jti"),
    )
    op.create_index(
        "idx_auth_refresh_sessions_user",
        "auth_refresh_sessions",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_auth_refresh_sessions_org",
        "auth_refresh_sessions",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "idx_auth_refresh_sessions_session",
        "auth_refresh_sessions",
        ["session_id"],
    )
    op.create_index(
        "idx_auth_refresh_sessions_token_hash",
        "auth_refresh_sessions",
        ["refresh_token_hash"],
    )
    op.create_index(
        "idx_auth_refresh_sessions_expires",
        "auth_refresh_sessions",
        ["expires_at"],
    )
    op.create_index(
        "idx_auth_refresh_sessions_revoked",
        "auth_refresh_sessions",
        ["revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_auth_refresh_sessions_revoked", table_name="auth_refresh_sessions")
    op.drop_index("idx_auth_refresh_sessions_expires", table_name="auth_refresh_sessions")
    op.drop_index("idx_auth_refresh_sessions_token_hash", table_name="auth_refresh_sessions")
    op.drop_index("idx_auth_refresh_sessions_session", table_name="auth_refresh_sessions")
    op.drop_index("idx_auth_refresh_sessions_org", table_name="auth_refresh_sessions")
    op.drop_index("idx_auth_refresh_sessions_user", table_name="auth_refresh_sessions")
    op.drop_table("auth_refresh_sessions")

    op.drop_constraint("users_password_state_allowed", "users", type_="check")
    op.drop_column("users", "account_locked_until")
    op.drop_column("users", "account_locked_at")
    op.drop_column("users", "failed_login_attempts")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "password_state")
    op.drop_column("users", "hashed_password")
