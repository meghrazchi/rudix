#!/usr/bin/env python3
"""Backup freshness gate from the markers (R08-06, ``DEPLOY_BACKUP_GATE=marker``).

    python scripts/check_backup_freshness.py [--kinds postgres,qdrant] [--max-age-hours 26]

Reads ``<BACKUP_PREFIX>/<kind>/latest.json`` for every kind in BACKUP_KINDS (or --kinds)
and exits 1 when any is missing, unreadable, or older than BACKUP_MAX_AGE_HOURS (or
--max-age-hours), or when the bucket cannot be read. Prints one line per kind with its
status and age only: no bucket, key, path, or credential. The release workflow runs it
inside the api container (deploy/scripts/check_backup_markers.sh).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops.backup.freshness import check_freshness
from app.ops.backup.store import BackupStore


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check backup marker freshness.")
    parser.add_argument("--kinds", default=None, help="comma list; default BACKUP_KINDS")
    parser.add_argument("--max-age-hours", type=int, default=None)
    args = parser.parse_args(argv)
    if args.max_age_hours is not None and args.max_age_hours < 1:
        parser.error("--max-age-hours must be at least 1")
    return args


def main(
    argv: Sequence[str] | None = None,
    *,
    config: Any | None = None,
    store: BackupStore | None = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    args = _parse(argv)
    if config is None:
        from app.core.config import settings

        config = settings
    kinds = (
        [kind.strip() for kind in args.kinds.split(",") if kind.strip()]
        if args.kinds
        else list(config.backup_kinds)
    )
    max_age = args.max_age_hours or config.backup_max_age_hours
    if not kinds:
        print("backup freshness: no kinds configured", file=err)
        return 1
    try:
        store = store or BackupStore.from_settings(config, require_enabled=False)
        results = check_freshness(store, kinds, max_age_hours=max_age)
    except Exception as exc:
        print(f"backup freshness check failed: {type(exc).__name__}", file=err)
        return 1
    for result in results:
        print(result.describe(), file=out)
    failed = [result.kind for result in results if result.status != "fresh"]
    if failed:
        print(f"backup freshness failed (max age {max_age} h): {', '.join(failed)}", file=err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
