"""R04-09: partition tooling against a scratch table on PostgreSQL.

``rudix_partition_probe`` is shaped like ``usage_events`` (UUID id, organisation FK,
``created_at``/``updated_at``, JSON metadata, a check constraint, an
``(organization_id, created_at)`` index and a row-level security policy). It is created by
the test and dropped afterwards, together with its shadow and legacy copies. No application
table is converted.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")

from app.core import maintenance_metrics
from app.core.config import settings
from app.db import partition_migration as pm
from app.db.partitioning import (
    drop_expired_partitions,
    ensure_future_partitions,
    is_partitioned,
    list_partitions,
    report_missing_partition,
)
from app.domains.admin.repositories.retention import RETENTION_TABLES

pytestmark = pytest.mark.requires_postgres

PROBE = "rudix_partition_probe"
NOW = datetime(2026, 11, 27, 3, 45, tzinfo=UTC)
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "partition_table.py"
LEGACY = pm.legacy_name(PROBE, NOW)


async def _drop_probe(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table in (PROBE, pm.shadow_name(PROBE), LEGACY):
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))


@pytest_asyncio.fixture
async def probe(pg_engine: AsyncEngine) -> AsyncIterator[UUID]:
    await _drop_probe(pg_engine)
    org_id = uuid4()
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:id, :n, :n)"),
            {"id": org_id, "n": f"partition-probe-{org_id.hex}"},
        )
        await conn.execute(
            text(
                f"CREATE TABLE {PROBE} ("
                " id uuid NOT NULL,"
                " organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,"
                " event_type varchar(128) NOT NULL,"
                " cost_usd numeric(12, 6),"
                " metadata json NOT NULL DEFAULT '{}',"
                " created_at timestamptz NOT NULL DEFAULT now(),"
                " updated_at timestamptz NOT NULL DEFAULT now(),"
                f" CONSTRAINT pk_{PROBE} PRIMARY KEY (id),"
                " CONSTRAINT probe_cost_non_negative CHECK (cost_usd IS NULL OR cost_usd >= 0))"
            )
        )
        await conn.execute(
            text(f"CREATE INDEX idx_probe_org_created ON {PROBE} (organization_id, created_at)")
        )
        await conn.execute(text(f"ALTER TABLE {PROBE} ENABLE ROW LEVEL SECURITY"))
        await conn.execute(
            text(
                f"CREATE POLICY probe_tenant ON {PROBE} USING ("
                "current_setting('app.current_organization_id', true) IS NULL "
                "OR organization_id::text = current_setting('app.current_organization_id', true))"
            )
        )
    await _insert(pg_engine, org_id, [NOW - timedelta(days=d, minutes=d) for d in range(120)])
    try:
        yield org_id
    finally:
        await _drop_probe(pg_engine)
        async with pg_engine.begin() as conn:
            await conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org_id})


async def _insert(engine: AsyncEngine, org_id: UUID, created: list[datetime]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"INSERT INTO {PROBE} (id, organization_id, event_type, cost_usd, metadata,"
                " created_at, updated_at) VALUES (:id, :org, 'chat.query', 0.5,"
                " '{\"k\": 1}', :c, :c)"
            ),
            [{"id": uuid4(), "org": org_id, "c": value} for value in created],
        )


async def _convert(engine: AsyncEngine) -> None:
    await pm.create_shadow(engine, PROBE, now=NOW)
    assert (await pm.backfill(engine, PROBE, batch_size=1000)).complete
    await pm.swap(engine, PROBE, now=NOW)


def _gauge(table: str) -> float:
    return maintenance_metrics.PARTITION_MISSING.labels(table=table)._value.get()


@pytest.mark.asyncio
async def test_shadow_backfill_resume_swap_verify(pg_engine: AsyncEngine, probe: UUID) -> None:
    statements = await pm.create_shadow(pg_engine, PROBE, now=NOW)
    assert any("PRIMARY KEY (id, created_at)" in s for s in statements)
    async with pg_engine.connect() as conn:
        partitions = await list_partitions(conn, pm.shadow_name(PROBE))
    # 120 days back from 2026-11-27 starts in July; months ahead adds December.
    assert partitions == [f"{PROBE}_p2026{m:02d}" for m in range(7, 13)]

    first = await pm.backfill(pg_engine, PROBE, batch_size=25, max_batches=2)
    assert (first.rows_copied, first.batches, first.complete) == (50, 2, False)
    assert await pm.verify(pg_engine, PROBE, pm.shadow_name(PROBE)) != []

    resumed = await pm.backfill(pg_engine, PROBE, batch_size=25)
    assert (resumed.rows_copied, resumed.complete) == (70, True)
    assert await pm.verify(pg_engine, PROBE, pm.shadow_name(PROBE)) == []

    # Writes after the backfill: a new row and an update of a copied row reach the swap.
    # The new row is later than every copied row, as a real insert is. At exactly ``NOW`` it
    # tied the backfill cursor's created_at, and with ``updated_at`` older than the shadow it
    # was copied only when its random id sorted after the cursor's (flaky once the wall
    # clock passed ``NOW``).
    await _insert(pg_engine, probe, [NOW + timedelta(minutes=1)])
    async with pg_engine.begin() as conn:
        await conn.execute(
            text(
                f"UPDATE {PROBE} SET event_type = 'updated', updated_at = now() "
                f"WHERE created_at = (SELECT min(created_at) FROM {PROBE})"
            )
        )

    legacy = await pm.swap(pg_engine, PROBE, now=NOW)
    assert legacy == LEGACY
    assert await pm.verify(pg_engine, PROBE, LEGACY) == []

    async with pg_engine.connect() as conn:
        assert await is_partitioned(conn, PROBE)
        assert not await is_partitioned(conn, LEGACY)
        info = await pm.inspect_table(conn, PROBE)
        count = (await conn.execute(text(f"SELECT count(*) FROM {PROBE}"))).scalar_one()
        updated = (
            await conn.execute(text(f"SELECT count(*) FROM {PROBE} WHERE event_type='updated'"))
        ).scalar_one()
    assert (count, updated) == (121, 1)
    assert info.primary_key == f"pk_{PROBE}"
    assert {i.name for i in info.indexes} == {f"pk_{PROBE}", "idx_probe_org_created"}
    assert [p["policyname"] for p in info.policies] == ["probe_tenant"]
    assert info.rls_enabled
    assert len(info.outbound_fks) == 1


@pytest.mark.asyncio
async def test_one_month_range_query_prunes_to_one_partition(
    pg_engine: AsyncEngine, probe: UUID
) -> None:
    await _convert(pg_engine)
    async with pg_engine.connect() as conn:
        plan = (
            await conn.execute(
                text(
                    f"EXPLAIN SELECT count(*) FROM {PROBE} WHERE organization_id = :org "
                    "AND created_at >= '2026-10-01 00:00:00+00' "
                    "AND created_at < '2026-11-01 00:00:00+00'"
                ),
                {"org": probe},
            )
        ).all()
    text_plan = "\n".join(str(row[0]) for row in plan)
    scanned = {name for name in await _partition_names(pg_engine) if name in text_plan}
    assert scanned == {f"{PROBE}_p202610"}, text_plan


async def _partition_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        return await list_partitions(conn, PROBE)


@pytest.mark.asyncio
async def test_ensure_creates_next_month_and_gauge_flips(
    pg_engine: AsyncEngine, probe: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    await _convert(pg_engine)
    later = datetime(2026, 12, 15, tzinfo=UTC)
    async with pg_engine.begin() as conn:
        assert await report_missing_partition(conn, PROBE, now=later) is True
    assert _gauge(PROBE) == 1

    async with pg_engine.begin() as conn:
        result = await ensure_future_partitions(conn, PROBE, now=later, months_ahead=1)
    assert result.created == (f"{PROBE}_p202701",)
    assert result.next_month_missing is False
    assert _gauge(PROBE) == 0

    async with pg_engine.begin() as conn:
        again = await ensure_future_partitions(conn, PROBE, now=later, months_ahead=1)
    assert again.created == ()
    await _insert(pg_engine, probe, [datetime(2027, 1, 10, tzinfo=UTC)])


@pytest.mark.asyncio
async def test_drop_expired_partitions(pg_engine: AsyncEngine, probe: UUID) -> None:
    await _convert(pg_engine)
    async with pg_engine.begin() as conn:
        dropped = await drop_expired_partitions(
            conn, PROBE, cutoff=datetime(2026, 9, 1, tzinfo=UTC)
        )
    assert dropped == [f"{PROBE}_p202607", f"{PROBE}_p202608"]
    remaining = await _partition_names(pg_engine)
    assert remaining[0] == f"{PROBE}_p202609"
    async with pg_engine.connect() as conn:
        oldest = (await conn.execute(text(f"SELECT min(created_at) FROM {PROBE}"))).scalar_one()
    assert oldest >= datetime(2026, 9, 1, tzinfo=UTC)
    async with pg_engine.begin() as conn:
        assert await drop_expired_partitions(conn, PROBE, cutoff=datetime(2026, 9, 1)) == []


@pytest.mark.asyncio
async def test_ensure_is_noop_on_unpartitioned_app_tables(pg_engine: AsyncEngine) -> None:
    async with pg_engine.begin() as conn:
        for table in RETENTION_TABLES:
            assert not await is_partitioned(conn, table)
            result = await ensure_future_partitions(conn, table, now=NOW)
            assert (result.partitioned, result.created) == (False, ())
            assert await drop_expired_partitions(conn, table, cutoff=NOW) == []
            assert await report_missing_partition(conn, table, now=NOW) is False
        await conn.rollback()


@pytest.mark.asyncio
async def test_inbound_foreign_key_blocks_conversion(pg_engine: AsyncEngine) -> None:
    async with pg_engine.connect() as conn:
        info = await pm.inspect_table(conn, "authorization_decision_logs")
    assert any("authorization_conflicts" in blocker for blocker in info.blockers)
    with pytest.raises(pm.PartitionMigrationError):
        pm.build_create_shadow_sql(info, now=NOW)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("partition_table", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_plan_dry_run_and_verify(
    pg_migrated_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    monkeypatch.setattr(script, "_database_url", lambda: pg_migrated_url)

    assert script.main(["plan", "usage_events"]) == 0
    out = capsys.readouterr().out
    assert "preconditions: ok" in out and "shadow: usage_events_partitioned" in out

    assert script.main(["plan", "authorization_decision_logs"]) == 1
    assert "BLOCKER" in capsys.readouterr().out

    assert script.main(["create-shadow", "usage_events", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "PARTITION BY RANGE (created_at)" in out
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in out

    assert script.main(["backfill", "usage_events", "--dry-run"]) == 0
    assert "ON CONFLICT DO NOTHING" in capsys.readouterr().out

    assert script.main(["swap", "usage_events", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "RENAME TO" in out
    assert "SET LOCAL lock_timeout = '5s'" in out
    assert 'LOCK TABLE "usage_events" IN ACCESS EXCLUSIVE MODE' in out
    assert script.main(["swap", "authorization_decision_logs", "--dry-run"]) == 1

    assert script.main(["verify", "usage_events", "--against", "usage_events"]) == 0
    assert "match" in capsys.readouterr().out

    assert script.main(["swap", "authorization_decision_logs"]) == 1


def test_partition_month_helpers() -> None:
    info = pm.TableInfo(table=PROBE, columns=["id", "created_at"], primary_key=None)
    assert pm.partition_months(info, now=NOW) == [date(2026, 11, 1), date(2026, 12, 1)]
