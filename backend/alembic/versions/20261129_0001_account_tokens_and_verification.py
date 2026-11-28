"""account one-time tokens and email verification (R09-01 schema, 0.9.0 S1)

Revision ID: 20261129_0001
Revises: 20261128_0003
Create Date: 2026-11-29 00:00:00.000000

Adds the storage the 0.9.0 account flows use:

- ``auth_one_time_tokens``: single-use tokens (email verification, password reset, MFA
  challenge and enrolment, step-up, SAML request and assertion ids). Only the SHA-256 hex
  digest of a token is stored (unique), never the raw value.
- ``users.email_verified_at`` (nullable): when the user proved the mailbox.
- ``email_delivery_logs`` and ``user_notification_preferences``: the ``event_type`` CHECK
  constraints are replaced by the full ``EmailEventType`` list, which adds
  ``email_verification`` and ``password_reset`` (and ``onboarding_reminder``, which the model
  allowed since F353 but no migration had added).

Data-safety notes:
- Additive only: one new, empty table and one nullable column (metadata only on
  PostgreSQL 11+). No existing row changes.
- The replacement CHECK constraints only widen the allowed list. On PostgreSQL they are added
  ``NOT VALID`` and then validated in a separate statement, so the large
  ``email_delivery_logs`` table is scanned under ``SHARE UPDATE EXCLUSIVE`` (reads and writes
  continue) instead of ``ACCESS EXCLUSIVE``. Every statement runs after
  ``SET LOCAL lock_timeout = '5s'``; rerun after a blocking transaction ends.
- ``auth_one_time_tokens`` is a lookup table for row-level security (tokens are read before a
  tenant is bound): it gets the lookup policy of ``app.db.rls`` from a literal list
  (``tests/test_rls_coverage.py`` checks it against ``RLS_LOOKUP_TABLES_0_9_0``).

Rollback:
- ``downgrade`` drops the policy, the token table, and ``users.email_verified_at``, and puts
  back the previous CHECK lists (``NOT VALID``, so rows written with the new event types do
  not block the downgrade; they stay readable). Outstanding verification and reset links
  stop working and every verification timestamp is lost. Run it only before any production
  use of the 0.9.0 account flows.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.rls import TENANT_RLS_POLICY_NAME, build_lookup_policy_sql

revision: str = "20261129_0001"
down_revision: str | None = "20261128_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LOOKUP_TABLES: tuple[str, ...] = ("auth_one_time_tokens",)

TOKEN_PURPOSES: tuple[str, ...] = (
    "email_verification",
    "password_reset",
    "mfa_challenge",
    "mfa_enrolment",
    "step_up",
    "saml_request",
    "saml_assertion",
)

# Literal lists: later enum edits must not change what this revision did.
OLD_EVENT_TYPES: tuple[str, ...] = (
    "invite_received",
    "upload_failed",
    "upload_indexed",
    "connector_sync_failed",
    "billing_warning",
    "quota_warning",
    "security_alert",
)
NEW_EVENT_TYPES: tuple[str, ...] = (
    *OLD_EVENT_TYPES,
    "onboarding_reminder",
    "email_verification",
    "password_reset",
)

# (table, constraint name as created by 20260609_0005 under the naming convention)
EVENT_TYPE_CONSTRAINTS: tuple[tuple[str, str], ...] = (
    ("email_delivery_logs", "ck_email_delivery_logs_email_delivery_logs_event_type_allowed"),
    (
        "user_notification_preferences",
        "ck_user_notification_preferences_user_notif_pref_event__ba46",
    ),
)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _in_list(values: tuple[str, ...]) -> str:
    return "event_type IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _replace_event_type_checks(values: tuple[str, ...], *, validate: bool) -> None:
    for table, name in EVENT_TYPE_CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({_in_list(values)}) NOT VALID"
        )
        if validate:
            op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    if _is_postgresql():
        op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "auth_one_time_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("session_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_ip", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("token_hash", name="uq_auth_one_time_tokens_token_hash"),
        sa.CheckConstraint(
            "purpose IN (" + ", ".join(f"'{p}'" for p in TOKEN_PURPOSES) + ")",
            name=op.f("ck_auth_one_time_tokens_purpose_allowed"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_auth_one_time_tokens_attempt_count_non_negative")
        ),
        sa.CheckConstraint(
            "max_attempts >= 1", name=op.f("ck_auth_one_time_tokens_max_attempts_positive")
        ),
    )
    op.create_index(
        "idx_auth_one_time_tokens_user_purpose", "auth_one_time_tokens", ["user_id", "purpose"]
    )
    op.create_index("idx_auth_one_time_tokens_expires", "auth_one_time_tokens", ["expires_at"])
    op.create_index(
        "idx_auth_one_time_tokens_purpose_consumed",
        "auth_one_time_tokens",
        ["purpose", "consumed_at"],
    )
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    if _is_postgresql():
        _replace_event_type_checks(NEW_EVENT_TYPES, validate=True)
        for table in LOOKUP_TABLES:
            for statement in build_lookup_policy_sql(table):
                op.execute(statement)


def downgrade() -> None:
    if _is_postgresql():
        op.execute("SET LOCAL lock_timeout = '5s'")
        for table in LOOKUP_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON {table}")
        _replace_event_type_checks(OLD_EVENT_TYPES, validate=False)
    op.drop_column("users", "email_verified_at")
    op.drop_index("idx_auth_one_time_tokens_purpose_consumed", table_name="auth_one_time_tokens")
    op.drop_index("idx_auth_one_time_tokens_expires", table_name="auth_one_time_tokens")
    op.drop_index("idx_auth_one_time_tokens_user_purpose", table_name="auth_one_time_tokens")
    op.drop_table("auth_one_time_tokens")
