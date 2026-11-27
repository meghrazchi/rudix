"""organisation audit log retention override (R04-09)

Revision ID: 20261127_0005
Revises: 20261127_0004
Create Date: 2026-11-27 00:00:00.000000

Adds ``organization_governance_policies.audit_log_retention_days``: an optional per-organisation
override of ``RETENTION_AUDIT_LOGS_DAYS``. NULL (every existing row) means "use the platform
default", and the platform default is "keep", so nothing is deleted until an operator or an
organisation admin sets a window. The check constraint enforces the 30-day floor.

Data-safety notes:
- Additive and nullable with no default: on PostgreSQL 11+ ``ADD COLUMN`` is metadata only.
- ``ADD CONSTRAINT ... CHECK`` validates existing rows; every row is NULL and the table holds
  one row per organisation, so the scan is trivial. ``lock_timeout = '5s'`` makes the
  migration fail instead of queueing behind a long transaction.
- Rollback: downgrade drops the constraint and the column. Overrides set since the upgrade
  are lost; the platform default applies again.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261127_0005"
down_revision: str | None = "20261127_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

TABLE = "organization_governance_policies"
COLUMN = "audit_log_retention_days"
CONSTRAINT = "ck_organization_governance_policies_audit_retention_min"
CONDITION = "audit_log_retention_days IS NULL OR audit_log_retention_days >= 30"


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgresql():
        with op.batch_alter_table(TABLE) as batch:
            batch.add_column(sa.Column(COLUMN, sa.Integer(), nullable=True))
            batch.create_check_constraint(op.f(CONSTRAINT), CONDITION)
        return
    op.execute("SET lock_timeout = '5s'")
    op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    op.create_check_constraint(op.f(CONSTRAINT), TABLE, CONDITION)
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not _is_postgresql():
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(op.f(CONSTRAINT), type_="check")
            batch.drop_column(COLUMN)
        return
    op.execute("SET lock_timeout = '5s'")
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.drop_column(TABLE, COLUMN)
    op.execute("RESET lock_timeout")
