"""chunk, outbox, connector job, and agent run indexes built concurrently (R06-01 part 2)

Revision ID: 20261128_0003
Revises: 20261128_0002
Create Date: 2026-11-28 00:00:02.000000

Indexes for the 0.6.0 worker paths:

- ``idx_chunks_org_document`` ``(organization_id, document_id)`` and ``idx_chunks_fts_vector``
  (GIN on ``fts_vector``) on ``document_chunks`` (chain B reads and writes them).
- ``idx_outbox_pending`` ``(status, available_at)``: the ``outbox.relay`` scan.
- ``idx_connector_sync_jobs_due`` ``(status, next_run_at)``: the due-job scan (chain D).
- ``idx_agent_runs_lease`` ``(status, lease_expires_at)``: expired agent leases (chain C).
- ``idx_agent_tool_calls_run_idem`` ``(agent_run_id, idempotency_key_hash)``, non-unique:
  existing rows may repeat a key, so uniqueness is not enforced here.

Data-safety notes:
- Additive only: creates indexes, changes no rows or columns.
- On PostgreSQL each index is built with ``CREATE INDEX CONCURRENTLY`` inside an
  autocommit block, so the build does not block reads or writes on the table (the
  ``20261127_0002`` pattern). The build runs with ``statement_timeout = 0`` and
  ``lock_timeout = '10s'``.
- Rerun-safe: a failed concurrent build leaves an INVALID index; the upgrade drops an index
  of the same name only when ``pg_index.indisvalid`` is false and then creates it with
  ``IF NOT EXISTS``, so a valid index is never rebuilt.
- The GIN index is PostgreSQL only (``fts_vector`` does not exist on SQLite).
- Rollback: downgrade drops the indexes (concurrently on PostgreSQL). Nothing depends on
  them for correctness.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261128_0003"
down_revision: str | None = "20261128_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# (index name, table, columns, postgresql_using or None).
INDEXES: tuple[tuple[str, str, tuple[str, ...], str | None], ...] = (
    ("idx_chunks_org_document", "document_chunks", ("organization_id", "document_id"), None),
    ("idx_chunks_fts_vector", "document_chunks", ("fts_vector",), "gin"),
    ("idx_outbox_pending", "outbox_messages", ("status", "available_at"), None),
    ("idx_connector_sync_jobs_due", "connector_sync_jobs", ("status", "next_run_at"), None),
    ("idx_agent_runs_lease", "agent_runs", ("status", "lease_expires_at"), None),
    (
        "idx_agent_tool_calls_run_idem",
        "agent_tool_calls",
        ("agent_run_id", "idempotency_key_hash"),
        None,
    ),
)
_POSTGRESQL_ONLY = frozenset({"idx_chunks_fts_vector"})

_INDEX_VALID_SQL = sa.text(
    "SELECT i.indisvalid FROM pg_index i "
    "JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relname = :name AND n.nspname = current_schema()"
)


def _drop_if_invalid(name: str) -> None:
    valid = op.get_bind().execute(_INDEX_VALID_SQL, {"name": name}).scalar()
    if valid is False:
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        for name, table, columns, _ in INDEXES:
            if name not in _POSTGRESQL_ONLY:
                op.create_index(name, table, list(columns))
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '10s'")
        try:
            for name, table, columns, using in INDEXES:
                _drop_if_invalid(name)
                extra = {"postgresql_using": using} if using else {}
                op.create_index(
                    name,
                    table,
                    list(columns),
                    postgresql_concurrently=True,
                    if_not_exists=True,
                    **extra,
                )
        finally:
            op.execute("RESET lock_timeout")
            op.execute("RESET statement_timeout")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        for name, table, _, _ in reversed(INDEXES):
            if name not in _POSTGRESQL_ONLY:
                op.drop_index(name, table_name=table)
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '10s'")
        try:
            for name, _, _, _ in reversed(INDEXES):
                op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')
        finally:
            op.execute("RESET lock_timeout")
