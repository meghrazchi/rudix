"""membership, usage event, and audit log user indexes (R04-02)

Revision ID: 20261127_0003
Revises: 20261127_0002
Create Date: 2026-11-27 00:00:00.000000

Data-safety notes:
- Additive only: creates indexes, changes no rows or columns.
- On PostgreSQL each index is built with ``CREATE INDEX CONCURRENTLY`` inside an
  autocommit block, so the build does not block reads or writes on the table. The build
  runs with ``statement_timeout = 0`` (``usage_events`` and ``audit_logs`` can be large) and
  ``lock_timeout = '10s'`` (gives up instead of queueing behind a long transaction).
- Rerun-safe: a concurrent build that failed leaves an INVALID index behind; the upgrade
  drops an index of the same name only when ``pg_index.indisvalid`` is false and then
  creates it with ``IF NOT EXISTS``, so a valid index is never rebuilt.
- Rollback: downgrade drops the indexes (concurrently on PostgreSQL). Old code does not
  depend on them, so rolling back the application without downgrading is also safe.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261127_0003"
down_revision: str | None = "20261127_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# (index name, table, columns); a column with a space is an ordered expression.
INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("idx_organization_members_user", "organization_members", ("user_id",)),
    ("idx_usage_events_user_created", "usage_events", ("user_id", "created_at")),
    ("idx_audit_logs_user_created", "audit_logs", ("user_id", "created_at")),
)

_INDEX_VALID_SQL = sa.text(
    "SELECT i.indisvalid FROM pg_index i "
    "JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relname = :name AND n.nspname = current_schema()"
)


def _columns(columns: tuple[str, ...]) -> list[str | sa.TextClause]:
    return [sa.text(column) if " " in column else column for column in columns]


def _drop_if_invalid(name: str) -> None:
    valid = op.get_bind().execute(_INDEX_VALID_SQL, {"name": name}).scalar()
    if valid is False:
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        for name, table, columns in INDEXES:
            op.create_index(name, table, _columns(columns))
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '10s'")
        try:
            for name, table, columns in INDEXES:
                _drop_if_invalid(name)
                op.create_index(
                    name,
                    table,
                    _columns(columns),
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")
            op.execute("RESET statement_timeout")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        for name, table, _ in reversed(INDEXES):
            op.drop_index(name, table_name=table)
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '10s'")
        try:
            for name, _, _ in reversed(INDEXES):
                op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')
        finally:
            op.execute("RESET lock_timeout")
