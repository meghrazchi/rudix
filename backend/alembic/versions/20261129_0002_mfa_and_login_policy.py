"""MFA factors, recovery codes, org login policy, session auth method (R09-02 schema, S1)

Revision ID: 20261129_0002
Revises: 20261129_0001
Create Date: 2026-11-29 00:00:01.000000

Adds:

- ``user_mfa_factors``: one row per enrolment (TOTP today); the secret is stored encrypted.
  A partial unique index allows at most one ``active`` factor per user and type.
- ``user_mfa_recovery_codes``: keyed hashes of single-use recovery codes.
- ``org_login_policies``: per-organisation MFA requirement (``mfa_required`` false,
  ``mfa_grace_period_days`` 7, ``mfa_required_since``). No row keeps today's behaviour.
- ``auth_refresh_sessions.auth_method`` (``password`` default, or ``sso``) and
  ``.mfa_verified_at`` (nullable).

Data-safety notes:
- Additive only: three new, empty tables and two columns on ``auth_refresh_sessions`` (a
  large table). ``auth_method`` is ``NOT NULL`` with a constant default, which PostgreSQL 11+
  adds as metadata only (no rewrite, existing sessions read ``password``). Its CHECK
  constraint is added ``NOT VALID`` and validated in a second statement (``SHARE UPDATE
  EXCLUSIVE``). Every statement runs after ``SET LOCAL lock_timeout = '5s'``.
- ``user_mfa_*`` have no tenant column (a factor protects the user in every organisation),
  so they get no policy, like ``users``. ``org_login_policies`` is read at login before a
  tenant is bound: it gets the lookup policy from a literal list
  (``tests/test_rls_coverage.py`` checks it against ``RLS_LOOKUP_TABLES_0_9_0``).

Rollback:
- ``downgrade`` drops the policy, the three tables, and the two session columns. Every MFA
  enrolment, recovery code, and organisation login policy is lost, and users who had MFA sign
  in with a password alone afterwards. Run it only before any production use of MFA.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.rls import TENANT_RLS_POLICY_NAME, build_lookup_policy_sql

revision: str = "20261129_0002"
down_revision: str | None = "20261129_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LOOKUP_TABLES: tuple[str, ...] = ("org_login_policies",)
AUTH_METHOD_CHECK = "ck_auth_refresh_sessions_auth_method_allowed"


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _user_fk() -> sa.Column:
    return sa.Column(
        "user_id",
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )


def _create_mfa_tables() -> None:
    op.create_table(
        "user_mfa_factors",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("factor_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("secret_key_id", sa.String(length=128), nullable=True),
        sa.Column("secret_algorithm", sa.String(length=64), nullable=True),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "factor_type IN ('totp')", name=op.f("ck_user_mfa_factors_factor_type_allowed")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active')", name=op.f("ck_user_mfa_factors_status_allowed")
        ),
    )
    op.create_index(
        "uq_user_mfa_factors_user_type_active",
        "user_mfa_factors",
        ["user_id", "factor_type"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "user_mfa_recovery_codes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column(
            "factor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("user_mfa_factors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("code_hash", name="uq_user_mfa_recovery_codes_code_hash"),
    )
    op.create_index("idx_user_mfa_recovery_codes_user", "user_mfa_recovery_codes", ["user_id"])


def _create_login_policies() -> None:
    op.create_table(
        "org_login_policies",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mfa_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mfa_grace_period_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("mfa_required_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", name="uq_org_login_policies_organization_id"),
        sa.CheckConstraint(
            "mfa_grace_period_days >= 0 AND mfa_grace_period_days <= 90",
            name=op.f("ck_org_login_policies_mfa_grace_period_days_range"),
        ),
    )


def upgrade() -> None:
    if _is_postgresql():
        op.execute("SET LOCAL lock_timeout = '5s'")
    _create_mfa_tables()
    _create_login_policies()
    op.add_column(
        "auth_refresh_sessions",
        sa.Column("auth_method", sa.String(length=16), nullable=False, server_default="password"),
    )
    op.add_column(
        "auth_refresh_sessions",
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    if _is_postgresql():
        op.execute(
            f"ALTER TABLE auth_refresh_sessions ADD CONSTRAINT {AUTH_METHOD_CHECK} "
            "CHECK (auth_method IN ('password', 'sso')) NOT VALID"
        )
        op.execute(f"ALTER TABLE auth_refresh_sessions VALIDATE CONSTRAINT {AUTH_METHOD_CHECK}")
        for table in LOOKUP_TABLES:
            for statement in build_lookup_policy_sql(table):
                op.execute(statement)


def downgrade() -> None:
    if _is_postgresql():
        op.execute("SET LOCAL lock_timeout = '5s'")
        for table in LOOKUP_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON {table}")
        op.execute(
            f"ALTER TABLE auth_refresh_sessions DROP CONSTRAINT IF EXISTS {AUTH_METHOD_CHECK}"
        )
    op.drop_column("auth_refresh_sessions", "mfa_verified_at")
    op.drop_column("auth_refresh_sessions", "auth_method")
    op.drop_table("org_login_policies")
    op.drop_index("idx_user_mfa_recovery_codes_user", table_name="user_mfa_recovery_codes")
    op.drop_table("user_mfa_recovery_codes")
    op.drop_index("uq_user_mfa_factors_user_type_active", table_name="user_mfa_factors")
    op.drop_table("user_mfa_factors")
