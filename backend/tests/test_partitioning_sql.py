"""R04-09: pure SQL builders of the partition tooling (no database needed)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import partition_migration as pm
from app.db.partitioning import (
    add_months,
    create_partition_sql,
    drop_expired_partitions,
    ensure_future_partitions,
    is_partitioned,
    list_partitions,
    lock_timeout_sql,
    month_start,
    monthly_partition_name,
    months_between,
    parse_partition_month,
    quote_identifier,
    report_missing_partition,
)

NOW = datetime(2026, 11, 27, 3, 45, tzinfo=UTC)


def _info() -> pm.TableInfo:
    return pm.TableInfo(
        table="usage_events",
        columns=["id", "organization_id", "created_at", "updated_at"],
        primary_key="pk_usage_events",
        indexes=[
            pm.IndexInfo(
                "pk_usage_events",
                "CREATE UNIQUE INDEX pk_usage_events ON public.usage_events USING btree (id)",
                True,
                True,
            ),
            pm.IndexInfo(
                "idx_usage_org_created",
                "CREATE INDEX idx_usage_org_created ON public.usage_events "
                "USING btree (organization_id, created_at)",
                False,
                False,
            ),
            pm.IndexInfo(
                "uq_usage_request",
                "CREATE UNIQUE INDEX uq_usage_request ON public.usage_events "
                "USING btree (request_id)",
                True,
                False,
            ),
            pm.IndexInfo(
                "usage_events_backfill_cursor",
                "CREATE INDEX usage_events_backfill_cursor ON public.usage_events "
                "USING btree (created_at, id)",
                False,
                False,
            ),
        ],
        outbound_fks=[
            ("fk_usage_events_org", "FOREIGN KEY (organization_id) REFERENCES organizations(id)")
        ],
        policies=[
            {
                "policyname": "tenant_isolation",
                "permissive": "PERMISSIVE",
                "roles": ["public"],
                "cmd": "ALL",
                "qual": "(organization_id IS NOT NULL)",
                "with_check": "(organization_id IS NOT NULL)",
            }
        ],
        rls_enabled=True,
        rls_forced=True,
        grants=[("rudix_app", "SELECT"), ("PUBLIC", "SELECT")],
        min_created_at=datetime(2026, 9, 3, tzinfo=UTC),
        max_created_at=datetime(2026, 11, 20, tzinfo=UTC),
    )


def test_month_helpers() -> None:
    assert month_start(datetime(2026, 12, 31, 23, 30, tzinfo=UTC)) == date(2026, 12, 1)
    assert month_start(datetime(2026, 12, 31, 23, 30)) == date(2026, 12, 1)
    assert month_start(date(2026, 2, 14)) == date(2026, 2, 1)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert months_between(date(2026, 11, 5), date(2027, 1, 2)) == [
        date(2026, 11, 1),
        date(2026, 12, 1),
        date(2027, 1, 1),
    ]
    assert monthly_partition_name("usage_events", date(2027, 1, 1)) == "usage_events_p202701"
    assert parse_partition_month("usage_events", "usage_events_p202701") == date(2027, 1, 1)
    assert parse_partition_month("usage_events", "usage_events_p202713") is None
    assert parse_partition_month("usage_events", "usage_events_default") is None


def test_identifier_and_lock_timeout_validation() -> None:
    assert quote_identifier("usage_events") == '"usage_events"'
    for bad in ("Usage", "a;drop", "x" * 64, ""):
        with pytest.raises(ValueError):
            quote_identifier(bad)
    assert lock_timeout_sql("750ms") == "SET LOCAL lock_timeout = '750ms'"
    with pytest.raises(ValueError):
        lock_timeout_sql("5s'; DROP TABLE x")
    with pytest.raises(ValueError):
        monthly_partition_name("x" * 60, date(2026, 1, 1))


def test_create_partition_sql() -> None:
    assert create_partition_sql("usage_events", date(2026, 12, 1)) == (
        'CREATE TABLE IF NOT EXISTS "usage_events_p202612" PARTITION OF "usage_events" '
        "FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00')"
    )
    sql = create_partition_sql(
        "usage_events", date(2026, 12, 1), parent="usage_events_partitioned", if_not_exists=False
    )
    assert sql.startswith('CREATE TABLE "usage_events_p202612" PARTITION OF "usage_events_part')


def test_build_create_shadow_sql() -> None:
    since = datetime(2026, 11, 27, 1, 0, tzinfo=UTC)
    statements = pm.build_create_shadow_sql(_info(), now=NOW, since=since)
    joined = "\n".join(statements)
    assert statements[0].endswith("PARTITION BY RANGE (created_at)")
    assert '"pk_usage_events_sh" PRIMARY KEY (id, created_at)' in joined
    assert 'CREATE INDEX "idx_usage_org_created_sh" ON "usage_events_partitioned"' in joined
    assert "uq_usage_request" not in joined
    assert "backfill_cursor" not in joined
    assert '"fk_usage_events_org_sh" FOREIGN KEY' in joined
    assert "ENABLE ROW LEVEL SECURITY" in joined and "FORCE ROW LEVEL SECURITY" in joined
    assert 'CREATE POLICY "tenant_isolation" ON "usage_events_partitioned" AS PERMISSIVE' in joined
    assert "TO PUBLIC USING ((organization_id IS NOT NULL)) WITH CHECK" in joined
    assert 'GRANT SELECT ON "usage_events_partitioned" TO "rudix_app"' in joined
    partitions = [s for s in statements if "PARTITION OF" in s]
    assert [p.split('"')[1] for p in partitions] == [
        "usage_events_p202609",
        "usage_events_p202610",
        "usage_events_p202611",
        "usage_events_p202612",
    ]
    assert statements[-1].endswith(f"'{pm.SHADOW_COMMENT_PREFIX}2026-11-27T01:00:00+00:00'")
    assert pm.skipped_indexes(_info()) == ["uq_usage_request"]


def test_blockers_stop_shadow_creation() -> None:
    info = _info()
    info.inbound_fks = [("authorization_conflicts", "fk_x")]
    info.columns = ["id"]
    assert info.blockers == [
        "missing column created_at",
        "foreign key fk_x on authorization_conflicts references usage_events",
    ]
    with pytest.raises(pm.PartitionMigrationError):
        pm.build_create_shadow_sql(info, now=NOW)


def test_build_swap_rename_sql() -> None:
    statements = pm.build_swap_rename_sql(_info(), now=NOW)
    assert statements[:2] == [
        'ALTER TABLE "usage_events" RENAME TO "usage_events_legacy_202611"',
        'ALTER TABLE "usage_events_partitioned" RENAME TO "usage_events"',
    ]
    assert 'ALTER INDEX "idx_usage_org_created" RENAME TO "idx_usage_org_created_l202611"' in (
        statements
    )
    assert 'ALTER INDEX "idx_usage_org_created_sh" RENAME TO "idx_usage_org_created"' in (
        statements
    )
    assert not any("uq_usage_request_sh" in s for s in statements)
    assert not any("backfill_cursor" in s for s in statements)
    assert (
        'ALTER TABLE "usage_events" RENAME CONSTRAINT "pk_usage_events_sh" TO "pk_usage_events"'
        in statements
    )
    assert statements[-1] == 'COMMENT ON TABLE "usage_events" IS NULL'


def test_name_helpers_respect_identifier_limit() -> None:
    long_name = "t" * 60
    assert len(pm.suffixed(long_name, "_partitioned")) == 63
    assert pm.legacy_name("usage_events", NOW) == "usage_events_legacy_202611"
    assert pm.cursor_index_name("usage_events") == "usage_events_backfill_cursor"


def test_backfill_and_checksum_sql() -> None:
    first = pm.backfill_batch_sql("usage_events", ["id", "created_at"], first=True)
    assert "WHERE TRUE" in first and "ON CONFLICT DO NOTHING" in first
    later = pm.backfill_batch_sql("usage_events", ["id", "created_at"], first=False)
    assert "(created_at, id) > (:last_created_at, :last_id)" in later
    assert "md5(string_agg(md5(x::text), '' ORDER BY id))" in pm.month_checksum_sql("t")
    assert pm.cursor_index_sql("usage_events").startswith("CREATE INDEX CONCURRENTLY")


@pytest.mark.asyncio
async def test_helpers_are_noops_on_non_postgres() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            assert await is_partitioned(conn, "usage_events") is False
            assert await list_partitions(conn, "usage_events") == []
            result = await ensure_future_partitions(conn, "usage_events", now=NOW)
            assert result.partitioned is False
            assert await drop_expired_partitions(conn, "usage_events", cutoff=NOW) == []
            assert await report_missing_partition(conn, "usage_events", now=NOW) is False
            with pytest.raises(ValueError):
                await ensure_future_partitions(conn, "usage_events", now=NOW, months_ahead=-1)
    finally:
        await engine.dispose()
