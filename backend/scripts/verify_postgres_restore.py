#!/usr/bin/env python3
"""Verify a restored PostgreSQL database (R08-04, contract 5.2.10).

    python scripts/verify_postgres_restore.py --database-url "$RESTORE_DATABASE_URL" \\
        [--expect-revision 20261128_0003] [--manifest manifest.json]
    python scripts/verify_postgres_restore.py --database-url "$SOURCE_URL" \\
        --write-manifest manifest.json [--tables documents,chat_messages]

Exits 0 only when ``alembic_version`` is the expected head (default: the head of the
shipped migrations), the required tables, RLS policies, primary keys, and key indexes exist,
and every manifest row-count floor holds. Prints table names and counts only, never data,
the URL, or credentials. ``--write-manifest`` records current counts as floors instead.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops import restore_verify


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a restored Rudix database.")
    parser.add_argument("--database-url", required=True, help="postgresql:// URL (not printed)")
    parser.add_argument("--expect-revision", default=None)
    parser.add_argument("--manifest", type=Path, default=None, help="row_count_floors JSON")
    parser.add_argument("--write-manifest", type=Path, default=None)
    parser.add_argument("--tables", default=None, help="--write-manifest: comma list")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
    connect: Any | None = None,
) -> int:
    args = _parse(argv)
    try:
        if args.write_manifest is not None:
            tables = (
                [name.strip() for name in args.tables.split(",") if name.strip()]
                if args.tables
                else list(restore_verify.MANIFEST_TABLES)
            )
            counts = asyncio.run(
                restore_verify.write_manifest(
                    args.database_url, args.write_manifest, tables=tables, connect=connect
                )
            )
            for table, count in sorted(counts.items()):
                print(f"floor   {table} {count}", file=out)
            return 0
        expected = args.expect_revision or restore_verify.expected_head()
        floors = restore_verify.load_manifest(args.manifest) if args.manifest else {}
        report = asyncio.run(
            restore_verify.verify_restore(
                args.database_url, expected_revision=expected, floors=floors, connect=connect
            )
        )
    except (ValueError, OSError) as exc:
        print(f"verify failed: {type(exc).__name__}: {exc}", file=err)
        return 1
    except Exception as exc:  # database errors may echo server details; type only
        print(f"verify failed: {type(exc).__name__}", file=err)
        return 1
    for line in report.lines:
        print(line, file=out)
    if not report.passed:
        print(f"restore verification failed: {report.failures} check(s)", file=err)
        return 1
    print("restore verification passed", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
