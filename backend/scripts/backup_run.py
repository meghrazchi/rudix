#!/usr/bin/env python3
"""Run one encrypted backup and write its marker (R08-06).

    python scripts/backup_run.py --kind postgres   # encrypts BACKUP_WORK_DIR/postgres.dump
    python scripts/backup_run.py --kind qdrant     # snapshots every deployment collection
    python scripts/backup_run.py --kind objects    # incremental mirror of MINIO_BUCKET

Needs BACKUP_ENABLED=true, BACKUP_BUCKET, and BACKUP_ENCRYPTION_KEY_FILE. The postgres kind
expects the dump that ``pg_dump -Fc`` (Compose ``backup-postgres-dump``, chart
initContainer) wrote into BACKUP_WORK_DIR. Prints one JSON line with the kind, completion
time, and size; never a key, URL, or credential. Exit 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

if __package__ in (None, ""):
    # Running as a script puts scripts/ (not backend/) on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops.backup.crypto import BackupCryptoError
from app.ops.backup.runner import RUN_KINDS, run_backup
from app.ops.backup.store import BackupConfigurationError

# Errors whose messages are written by this package and safe to print.
_SAFE_ERRORS = (BackupConfigurationError, BackupCryptoError, RuntimeError, ValueError)


def main(
    argv: Sequence[str] | None = None,
    *,
    config: Any | None = None,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
    **overrides: Any,
) -> int:
    parser = argparse.ArgumentParser(description="Run one encrypted Rudix backup.")
    parser.add_argument("--kind", required=True, choices=RUN_KINDS)
    args = parser.parse_args(argv)
    if config is None:
        from app.core.config import settings

        config = settings
    try:
        marker = run_backup(args.kind, config, **overrides)
    except _SAFE_ERRORS as exc:
        print(f"backup {args.kind} failed: {type(exc).__name__}: {exc}", file=err)
        return 1
    except Exception as exc:  # provider errors may carry endpoints; print the type only
        print(f"backup {args.kind} failed: {type(exc).__name__}", file=err)
        return 1
    data = marker.to_dict()
    payload = {key: data[key] for key in ("kind", "completed_at", "size_bytes")}
    print(json.dumps(payload, sort_keys=True), file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
