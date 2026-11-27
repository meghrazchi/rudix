"""outbox, vector index generations, and the 0.6.0 worker columns (R06-01 part 2)

Revision ID: 20261128_0002
Revises: 20261128_0001
Create Date: 2026-11-28 00:00:01.000000

Adds the schema the 0.6.0 chains use:

- ``outbox_messages``: Celery dispatches written in the transaction of the change that
  needs them and published after commit (or by the ``outbox.relay`` beat task).
- ``vector_index_generations`` (global, no tenant column) and
  ``vector_index_generation_documents`` (per organisation): bookkeeping for zero-downtime
  vector index rebuilds (chain A).
- Nullable columns: ``document_chunks.organization_id``, ``fts_config``, ``fts_vector``
  (chain B writes them; no ORM attribute yet), connector sync checkpoints and leases
  (chain D), and agent run leases (chain C).

Data-safety notes:
- Additive only: three new, empty tables and nullable columns, plus two ``NOT NULL
  DEFAULT 0`` integer columns. On PostgreSQL 11+ adding a column with a constant default
  is metadata only, so no table is rewritten. Every statement runs after
  ``SET LOCAL lock_timeout = '5s'``, so the migration fails instead of queueing behind a
  long transaction on a busy table (``document_chunks``); rerun it after the blocker ends.
- Indexes on the existing large tables are not built here; ``20261128_0003`` builds them
  ``CONCURRENTLY``. The new tables are empty, so their indexes are created inline.
- ``fts_vector`` is PostgreSQL only (``tsvector``); SQLite test databases skip it.
- ``external_items.last_seen_sync_run_id`` has no foreign key on purpose: sync runs are
  pruned independently of items.
- On PostgreSQL ``outbox_messages`` and ``vector_index_generation_documents`` get the
  strict tenant policy of ``app.db.rls`` (``build_strict_policy_sql``). The table list is a
  literal on purpose (``tests/test_rls_coverage.py`` checks it against
  ``RLS_STRICT_TABLES_0_6_0``).
- Rollback: downgrade drops the policies, the three tables, and the columns. Pending
  outbox rows are lost: a document whose dispatch was still pending stays ``uploaded`` (or
  ``delete_requested``) until it is re-queued, so drain the outbox first
  (``SELECT count(*) FROM outbox_messages WHERE status = 'pending'``). Old application
  code never reads the new columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.rls import TENANT_RLS_POLICY_NAME, build_strict_policy_sql

revision: str = "20261128_0002"
down_revision: str | None = "20261128_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

STRICT_TABLES: tuple[str, ...] = (
    "outbox_messages",
    "vector_index_generation_documents",
)


def _columns() -> tuple[tuple[str, sa.Column], ...]:
    """(table, column) in add order; dropped in reverse. Fresh objects per call."""
    return (
        ("document_chunks", sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=True)),
        ("document_chunks", sa.Column("fts_config", sa.String(length=32), nullable=True)),
        ("connector_sync_runs", sa.Column("checkpoint_cursor", sa.JSON(), nullable=True)),
        (
            "connector_sync_runs",
            sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=True),
        ),
        (
            "connector_sync_runs",
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        ),
        ("connector_sync_runs", sa.Column("lease_owner", sa.String(length=255), nullable=True)),
        (
            "connector_sync_runs",
            sa.Column("pages_committed", sa.Integer(), nullable=False, server_default="0"),
        ),
        (
            "connector_sync_jobs",
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        ),
        (
            "external_items",
            sa.Column("last_seen_sync_run_id", sa.Uuid(as_uuid=True), nullable=True),
        ),
        ("agent_runs", sa.Column("lease_owner", sa.String(length=255), nullable=True)),
        ("agent_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)),
        ("agent_runs", sa.Column("request_snapshot", sa.JSON(), nullable=True)),
        (
            "agent_runs",
            sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"),
        ),
    )


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _lock_timeout() -> None:
    if _is_postgresql():
        op.execute("SET LOCAL lock_timeout = '5s'")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _create_outbox() -> None:
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("queue", sa.String(length=64), nullable=True),
        sa.Column("kwargs", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=128), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_messages_dedupe_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'published', 'failed')",
            name=op.f("ck_outbox_messages_status_allowed"),
        ),
    )
    op.create_index(
        "idx_outbox_messages_org_created", "outbox_messages", ["organization_id", "created_at"]
    )


def _create_generations() -> None:
    op.create_table(
        "vector_index_generations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("alias_name", sa.String(length=128), nullable=False),
        sa.Column("collection_name", sa.String(length=128), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("vector_size", sa.Integer(), nullable=False),
        sa.Column("distance", sa.String(length=16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="building"),
        sa.Column("build_cursor", sa.JSON(), nullable=True),
        sa.Column("expected_points", sa.BigInteger(), nullable=True),
        sa.Column("indexed_points", sa.BigInteger(), nullable=True),
        sa.Column("documents_total", sa.Integer(), nullable=True),
        sa.Column("documents_done", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retire_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("collection_name", name="uq_vector_index_generations_collection"),
        sa.UniqueConstraint(
            "alias_name", "generation", name="uq_vector_index_generations_alias_generation"
        ),
        sa.CheckConstraint(
            "state IN ('building', 'verifying', 'active', 'retired', 'failed', 'dropped')",
            name=op.f("ck_vector_index_generations_state_allowed"),
        ),
    )
    op.create_table(
        "vector_index_generation_documents",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "generation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("vector_index_generations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("point_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "generation_id",
            "document_id",
            name="uq_vector_index_generation_documents_generation_document",
        ),
    )
    op.create_index(
        "idx_vector_index_generation_documents_org",
        "vector_index_generation_documents",
        ["organization_id", "generation_id"],
    )


def upgrade() -> None:
    _lock_timeout()
    _create_outbox()
    _create_generations()
    for table, column in _columns():
        op.add_column(table, column)
    if _is_postgresql():
        op.execute("ALTER TABLE document_chunks ADD COLUMN fts_vector tsvector")
        for table in STRICT_TABLES:
            for statement in build_strict_policy_sql(table):
                op.execute(statement)


def downgrade() -> None:
    _lock_timeout()
    if _is_postgresql():
        for table in STRICT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON {table}")
        op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS fts_vector")
    for table, column in reversed(_columns()):
        op.drop_column(table, column.name)
    op.drop_index(
        "idx_vector_index_generation_documents_org",
        table_name="vector_index_generation_documents",
    )
    op.drop_table("vector_index_generation_documents")
    op.drop_table("vector_index_generations")
    op.drop_index("idx_outbox_messages_org_created", table_name="outbox_messages")
    op.drop_table("outbox_messages")
