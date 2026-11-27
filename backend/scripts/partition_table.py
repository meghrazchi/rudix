"""Convert a table to monthly range partitions on created_at (operator tool, R04-09).

Never applied automatically. Rehearse on a staging copy with production volume first and
run the swap in a maintenance window; see docs/06_DATABASE_SCHEMA.md, "Retention and
partitioning". Set RETENTION_ENABLED=false for the whole conversion.

Usage:
    python scripts/partition_table.py plan <table>
    python scripts/partition_table.py create-shadow <table> [--months-ahead 1] [--dry-run]
    python scripts/partition_table.py backfill <table> [--batch-size 5000]
        [--max-batches N] [--dry-run]
    python scripts/partition_table.py swap <table> [--lock-timeout 5s] [--dry-run]
    python scripts/partition_table.py verify <table> [--against <other table>]

The connection comes from DATABASE_MIGRATION_URL when set, else DATABASE_URL. verify
compares <table> with its shadow before the swap, or pass --against <t>_legacy_<yyyymm>
after it. Exit codes: 0 success, 1 verification mismatch or precondition failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.db.partition_migration import (
    PartitionMigrationError,
    backfill,
    backfill_batch_sql,
    build_create_shadow_sql,
    build_swap_rename_sql,
    create_shadow,
    cursor_index_name,
    cursor_index_sql,
    inspect_table,
    partition_months,
    shadow_name,
    skipped_indexes,
    swap,
    verify,
)
from app.db.partitioning import lock_timeout_sql, monthly_partition_name, quote_identifier


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "create-shadow", "backfill", "swap", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("table")
        if name != "plan" and name != "verify":
            cmd.add_argument("--dry-run", action="store_true", help="print SQL, change nothing")
        if name == "create-shadow":
            cmd.add_argument("--months-ahead", type=int, default=1)
        if name == "backfill":
            cmd.add_argument("--batch-size", type=int, default=5000)
            cmd.add_argument("--max-batches", type=int, default=None)
        if name == "swap":
            cmd.add_argument("--lock-timeout", default="5s")
        if name == "verify":
            cmd.add_argument("--against", default=None)
    args = parser.parse_args(argv)
    quote_identifier(args.table)
    if getattr(args, "batch_size", 1) < 1:
        parser.error("--batch-size must be at least 1")
    return args


def _database_url() -> str:
    url = settings.database_migration_url or settings.database_url
    return str(url)


async def _plan(engine: AsyncEngine, table: str, now: datetime) -> int:
    async with engine.connect() as conn:
        info = await inspect_table(conn, table)
    months = partition_months(info, now=now)
    print(f"table: {table} (~{info.estimated_rows} rows)")
    print(f"created_at range: {info.min_created_at} .. {info.max_created_at}")
    print(f"shadow: {shadow_name(table)}, partitions: {len(months)}", end="")
    if months:
        first = monthly_partition_name(table, months[0])
        last = monthly_partition_name(table, months[-1])
        print(f" ({first} .. {last})")
    else:
        print()
    skipped = set(skipped_indexes(info))
    copied = [
        index.name
        for index in info.indexes
        if not index.primary
        and index.name not in skipped
        and index.name != cursor_index_name(table)
    ]
    print(f"indexes copied: {len(copied)}")
    for name in skipped_indexes(info):
        print(f"  skipped unique index without created_at: {name}")
    print(f"outbound foreign keys: {len(info.outbound_fks)}, policies: {len(info.policies)}")
    print("after swap: re-run deploy/sql/provision_roles.sql (grants are copied, verify them)")
    if info.blockers:
        for blocker in info.blockers:
            print(f"BLOCKER: {blocker}")
        return 1
    print("preconditions: ok (pause retention with RETENTION_ENABLED=false)")
    return 0


async def _run(args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    engine = create_async_engine(_database_url())
    try:
        if args.command == "plan":
            return await _plan(engine, args.table, now)
        if args.command == "create-shadow":
            if args.dry_run:
                async with engine.connect() as conn:
                    info = await inspect_table(conn, args.table)
                statements = build_create_shadow_sql(info, now=now, months_ahead=args.months_ahead)
                print(";\n".join([*statements, cursor_index_sql(args.table)]) + ";")
                return 0
            for statement in await create_shadow(
                engine, args.table, now=now, months_ahead=args.months_ahead
            ):
                print(statement)
            return 0
        if args.command == "backfill":
            if args.dry_run:
                async with engine.connect() as conn:
                    columns = (await inspect_table(conn, args.table)).columns
                print(backfill_batch_sql(args.table, columns, first=False) + ";")
                return 0
            result = await backfill(
                engine, args.table, batch_size=args.batch_size, max_batches=args.max_batches
            )
            state = "complete" if result.complete else "partial (rerun to resume)"
            print(f"copied {result.rows_copied} rows in {result.batches} batches: {state}")
            return 0
        if args.command == "swap":
            if args.dry_run:
                async with engine.connect() as conn:
                    info = await inspect_table(conn, args.table)
                if info.blockers:
                    raise PartitionMigrationError("; ".join(info.blockers))
                table = quote_identifier(args.table)
                shadow = quote_identifier(shadow_name(args.table))
                preamble = [
                    lock_timeout_sql(args.lock_timeout),
                    f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE",
                    f"LOCK TABLE {shadow} IN ACCESS EXCLUSIVE MODE",
                    "-- copy the delta (new and updated rows), then compare row counts",
                ]
                renames = build_swap_rename_sql(info, now=now)
                print("BEGIN;\n" + ";\n".join([*preamble, *renames]) + ";\nCOMMIT;")
                return 0
            legacy = await swap(engine, args.table, now=now, lock_timeout=args.lock_timeout)
            print(f"swapped: {args.table} is partitioned; old table kept as {legacy}")
            return 0
        other = args.against or shadow_name(args.table)
        mismatches = await verify(engine, args.table, other)
        if mismatches:
            print(f"MISMATCH between {args.table} and {other}: {', '.join(mismatches)}")
            return 1
        print(f"{args.table} and {other} match (row counts and checksums per month)")
        return 0
    except PartitionMigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
