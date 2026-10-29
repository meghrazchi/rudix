"""enable PostgreSQL row-level security policies on tenant tables.

Revision ID: 20260715_0001
Revises: 20260714_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.rls import TENANT_RLS_TABLES, build_disable_rls_sql, build_enable_rls_sql

revision: str = "20260715_0001"
down_revision: str | None = "20260714_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    existing_tables = set(sa.inspect(bind).get_table_names())
    for table_name in TENANT_RLS_TABLES:
        if table_name not in existing_tables:
            continue
        for statement in build_enable_rls_sql(table_name):
            op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    existing_tables = set(sa.inspect(bind).get_table_names())
    for table_name in reversed(TENANT_RLS_TABLES):
        if table_name not in existing_tables:
            continue
        for statement in build_disable_rls_sql(table_name):
            op.execute(statement)
