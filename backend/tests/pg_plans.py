"""Stable ``EXPLAIN`` checks on a reused PostgreSQL test database (R04-02, R04-04, R04-08).

The plan tests run on nearly empty tables with ``enable_seqscan = off``, so the planner
chooses between indexes by their physical size. Rows inserted and rolled back by earlier
tests (or earlier runs on the same database) leave dead index pages behind, and a bloated
index can then lose to a smaller, less selective one. ``REINDEX TABLE`` inside the test's
rolled-back transaction rebuilds every index of the table to its minimal size, so each run
sees the same index sizes as a fresh database. The rebuild is rolled back with the test.
"""

from __future__ import annotations

import re
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User

_TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


async def compact_indexes(session: AsyncSession, *tables: str) -> None:
    """Rebuild every index of ``tables`` in the current transaction (table owner only)."""
    for table in tables:
        if not _TABLE_NAME.fullmatch(table):
            raise ValueError(f"not a plain table name: {table!r}")
        await session.execute(text(f"REINDEX TABLE {table}"))


async def seed_usage_event_statistics(session: AsyncSession, rows: int = 500) -> None:
    """Give ``usage_events`` real statistics inside the rolled-back test transaction.

    Once autovacuum has analysed the empty table (``reltuples = 0``), every index path is
    estimated at one row, the costs tie, and the planner may pick
    ``idx_usage_events_user_created`` for an organisation range. Rows of another
    organisation plus ``ANALYZE`` make the organisation indexes win on selectivity, as they
    do on real data. ``ANALYZE`` counts this transaction's rows and its statistics are
    rolled back with the test.
    """
    organization = Organization(name="plan stats", slug=f"plan-stats-{uuid4().hex[:10]}")
    session.add(organization)
    await session.flush()
    await session.execute(
        text(
            "INSERT INTO usage_events "
            "(id, organization_id, event_type, metadata, timed_out, fallback_used, created_at) "
            "SELECT gen_random_uuid(), :org, 'plan_stats', '{}'::json, false, false, "
            "now() - make_interval(hours => n) FROM generate_series(1, :rows) AS n"
        ),
        {"org": organization.id, "rows": rows},
    )
    await session.execute(text("ANALYZE usage_events"))


async def seed_document_statistics(
    session: AsyncSession,
    rows: int = 500,
    *,
    organization_id: UUID | None = None,
    user_id: UUID | None = None,
) -> None:
    """Give ``documents`` real statistics inside the rolled-back test transaction (0.9.0).

    Same reason as :func:`seed_usage_event_statistics`: on an analysed, nearly empty table
    every organisation index is estimated at a handful of rows, and a bitmap scan of any
    ``(organization_id, ...)`` index plus a sort of five rows costs about as much as the
    ordered keyset index scan, so the plan flips between runs (it lost on a fresh database).
    ``rows`` older documents in the queried organisation (``organization_id``; a new
    organisation when omitted) plus ``ANALYZE`` make the ordered scan under ``LIMIT`` win by
    a wide margin, as on real data. Everything rolls back with the test.
    """
    suffix = uuid4().hex[:10]
    if organization_id is None or user_id is None:
        organization = Organization(name=f"plan stats {suffix}", slug=f"plan-stats-{suffix}")
        session.add(organization)
        await session.flush()
        user = User(organization_id=organization.id, email=f"plan-stats-{suffix}@example.com")
        session.add(user)
        await session.flush()
        organization_id, user_id = organization.id, user.id
    await session.execute(
        text(
            "INSERT INTO documents "
            "(id, organization_id, uploaded_by_user_id, filename, file_type, storage_bucket, "
            "storage_object_key, status, graph_extraction_status, created_at, updated_at) "
            "SELECT gen_random_uuid(), :org, :user, 'plan-stats-' || n || '.pdf', 'pdf', "
            "'documents', 'plan-stats/' || :suffix || '/' || n || '.pdf', 'indexed', 'pending', "
            "now() - make_interval(hours => n), now() FROM generate_series(1, :rows) AS n"
        ),
        {"org": organization_id, "user": user_id, "suffix": suffix, "rows": rows},
    )
    await session.execute(text("ANALYZE documents"))
