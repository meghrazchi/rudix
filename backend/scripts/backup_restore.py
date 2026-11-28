#!/usr/bin/env python3
"""Download and decrypt a backup to local files (R08-06).

    python scripts/backup_restore.py --kind postgres --latest --out /restore/postgres.dump
    python scripts/backup_restore.py --kind postgres --object-key rudix/postgres/<run>/... \\
        --out /restore/postgres.dump
    python scripts/backup_restore.py --kind qdrant --latest --out /restore/qdrant
    python scripts/backup_restore.py --kind objects --latest --out /restore/objects

``--latest`` reads the kind's marker and checks the artifact's SHA-256 against it. Keys: the
configured BACKUP_ENCRYPTION_KEY_FILE plus every ``--key-file`` (old keys kept after a
rotation); the key id in each file's header selects the right one. Reads the bucket with
BACKUP_BUCKET and the BACKUP_S3_* settings; BACKUP_ENABLED is not required. For postgres it
prints the pg_restore command to run next (with a placeholder, never a URL).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops.backup import restore as restore_ops
from app.ops.backup.crypto import BackupCryptoError
from app.ops.backup.runner import restore_keys
from app.ops.backup.store import BackupConfigurationError, BackupStore

KINDS = ("postgres", "qdrant", "objects", "neo4j")
_SAFE_ERRORS = (BackupConfigurationError, BackupCryptoError, RuntimeError, ValueError)

PG_RESTORE_HINT = (
    'pg_restore --no-owner --no-privileges --exit-on-error --dbname "$RESTORE_DATABASE_URL" {path}'
)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and decrypt a Rudix backup.")
    parser.add_argument("--kind", required=True, choices=KINDS)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--object-key", help="artifact (postgres, neo4j) or manifest key")
    target.add_argument("--latest", action="store_true", help="use the kind's marker")
    parser.add_argument("--out", required=True, type=Path, help="file (postgres) or directory")
    parser.add_argument(
        "--key-file", action="append", type=Path, default=[], help="older key (repeatable)"
    )
    return parser.parse_args(argv)


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
    object_key = None if args.latest else args.object_key
    try:
        keys = restore_keys(config, args.key_file)
        store = store or BackupStore.from_settings(config, require_enabled=False)
        if args.kind == "qdrant":
            result = restore_ops.restore_qdrant(
                store, keys, object_key=object_key, out_dir=args.out
            )
        elif args.kind == "objects":
            result = restore_ops.restore_objects(
                store, keys, object_key=object_key, out_dir=args.out
            )
        else:
            result = restore_ops.restore_file(
                store, keys, kind=args.kind, object_key=object_key, out=args.out
            )
    except _SAFE_ERRORS as exc:
        print(f"restore {args.kind} failed: {type(exc).__name__}: {exc}", file=err)
        return 1
    except Exception as exc:
        print(f"restore {args.kind} failed: {type(exc).__name__}", file=err)
        return 1
    print(
        f"restored {args.kind}: {len(result.files)} file(s), {result.plaintext_bytes} bytes",
        file=out,
    )
    if args.kind == "postgres":
        print("next: " + PG_RESTORE_HINT.format(path=args.out), file=out)
    elif args.kind == "qdrant":
        print(
            "next: upload each <collection>.snapshot to the scratch Qdrant "
            "(deploy/scripts/restore_drill.sh), then recreate aliases.json",
            file=out,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
