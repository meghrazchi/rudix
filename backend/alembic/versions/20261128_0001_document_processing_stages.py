"""document processing stages and stage artifacts (R06-01)

Revision ID: 20261128_0001
Revises: 20261127_0005
Create Date: 2026-11-28 00:00:00.000000

Adds the bookkeeping for staged, resumable ingestion:

- ``document_processing_stages``: one row per ``(document_id, run_id, stage)`` with status,
  attempt counter, lease owner and heartbeat, counts-only metrics, and an error code.
- ``document_stage_artifacts``: one row per ``(document_id, run_id, stage, part)`` holding
  zlib-compressed JSON a later stage reads (pages, cleaned pages, embedding batch
  summaries). Rows are deleted when the run finishes and when the document is deleted.

Data-safety notes:
- Additive only: two new, empty tables. No existing table, row, or column changes, so the
  indexes are created inline (an empty table builds them instantly).
- Both tables reference ``documents`` and ``organizations`` with ``ON DELETE CASCADE``, so
  removing a document or an organisation removes its stage rows and artifacts.
- On PostgreSQL both tables get the strict tenant policy of ``app.db.rls``
  (``build_strict_policy_sql``). ``FORCE ROW LEVEL SECURITY`` is not applied here; the
  ``deploy/sql/force_rls.sql`` script lists the tables for the non-owner role.
  ``lock_timeout = '5s'`` keeps the DDL from queueing behind a long transaction.
- The table list is a literal on purpose: later edits of ``app.db.rls`` must not change
  what this revision did (``tests/test_rls_coverage.py`` checks it).
- Rollback: downgrade drops the policies and both tables. Old application code never reads
  them; artifacts of runs in flight are lost and those runs restart from the first stage.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.rls import TENANT_RLS_POLICY_NAME, build_strict_policy_sql

revision: str = "20261128_0001"
down_revision: str | None = "20261127_0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

STRICT_TABLES: tuple[str, ...] = (
    "document_processing_stages",
    "document_stage_artifacts",
)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tenant_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
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
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "document_processing_stages",
        *_tenant_columns(),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("owner_task_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_ref", sa.String(length=512), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "document_id", "run_id", "stage", name="uq_document_processing_stages_run_stage"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_document_processing_stages_status_allowed"),
        ),
    )
    op.create_index(
        "idx_document_processing_stages_org_created",
        "document_processing_stages",
        ["organization_id", "created_at"],
    )
    op.create_table(
        "document_stage_artifacts",
        *_tenant_columns(),
        sa.Column("part", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "document_id",
            "run_id",
            "stage",
            "part",
            name="uq_document_stage_artifacts_run_stage_part",
        ),
    )
    if _is_postgresql():
        op.execute("SET lock_timeout = '5s'")
        for table in STRICT_TABLES:
            for statement in build_strict_policy_sql(table):
                op.execute(statement)
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    if _is_postgresql():
        op.execute("SET lock_timeout = '5s'")
        for table in STRICT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON {table}")
    op.drop_table("document_stage_artifacts")
    op.drop_index(
        "idx_document_processing_stages_org_created", table_name="document_processing_stages"
    )
    op.drop_table("document_processing_stages")
    if _is_postgresql():
        op.execute("RESET lock_timeout")
