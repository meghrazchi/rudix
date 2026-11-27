#!/usr/bin/env python3
"""Backfill document_chunks.organization_id and fts_vector synchronously (R06-09).

Runs the same batches as the ``documents.chunks.backfill_tenant`` task (one short
transaction per batch, ``SET LOCAL lock_timeout`` and ``statement_timeout``, primary-key
order, only rows whose organization_id is NULL), printing progress after each batch. It is
resumable: rerun it, or pass ``--cursor`` with the last id it printed. ``--dry-run`` prints
how many rows are left and changes nothing.

Run it with ``DATABASE_MAINTENANCE_URL`` set to the BYPASSRLS role. When it reports
``remaining=0``, apply ``deploy/sql/document_chunks_not_null.sql`` and set
``KEYWORD_SEARCH_TENANT_COLUMN=on``.

Usage:
    python scripts/backfill_chunk_tenant.py [--dry-run] [--batch-size 1000]
        [--cursor <uuid>] [--max-batches N]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import TextIO
from uuid import UUID

from app.workers.chunk_backfill_tasks import (
    BackfillBatch,
    BackfillProgress,
    SessionScope,
    backfill,
    count_remaining,
    default_session_scope,
)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="report remaining rows only")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--cursor", type=UUID, default=None, help="resume after this id")
    parser.add_argument("--max-batches", type=int, default=None)
    args = parser.parse_args(argv)
    if args.batch_size is not None and args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if args.max_batches is not None and args.max_batches < 1:
        parser.error("--max-batches must be at least 1")
    return args


async def run(
    argv: Sequence[str] | None = None,
    *,
    session_scope: SessionScope = default_session_scope,
    out: TextIO = sys.stdout,
) -> int:
    args = _parse_args(argv)
    remaining = await count_remaining(session_scope)
    print(f"remaining={remaining} mode={'DRY RUN' if args.dry_run else 'APPLY'}", file=out)
    if args.dry_run or remaining == 0:
        return 0

    def _report(batch: BackfillBatch, progress: BackfillProgress) -> None:
        print(
            f"batch={progress.batches} scanned={batch.scanned} updated={batch.updated} "
            f"total_updated={progress.updated} cursor={progress.cursor}",
            file=out,
            flush=True,
        )

    progress = await backfill(
        cursor=args.cursor,
        max_batches=args.max_batches,
        batch_size=args.batch_size,
        session_scope=session_scope,
        on_batch=_report,
    )
    remaining = await count_remaining(session_scope)
    print(
        f"done finished={progress.finished} updated={progress.updated} "
        f"remaining={remaining} cursor={progress.cursor}",
        file=out,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
