"""PostgreSQL backup: encrypt and upload a ``pg_dump -Fc`` file (R08-06).

The dump itself is produced by ``pg_dump -Fc`` in the ``postgres:16`` image (Compose
service ``backup-postgres-dump``, the chart CronJob's initContainer) into
``BACKUP_WORK_DIR``. This module never connects to PostgreSQL: it checks the file is a
custom-format dump, encrypts it, uploads it, writes the ``postgres`` marker, and removes the
plaintext dump.

Managed PostgreSQL with point-in-time recovery is the primary recovery path (docs/runbooks/
DR_DATABASE_CORRUPTION.md); this logical dump is the provider-independent fallback.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from app.core.logging import get_logger
from app.ops.backup.crypto import BackupKey
from app.ops.backup.markers import BackupMarker, run_stamp
from app.ops.backup.store import BackupStore, encrypt_and_upload

logger = get_logger("ops.backup.postgres")

KIND: Final[str] = "postgres"
DUMP_NAME: Final[str] = "postgres.dump"
# First bytes of a pg_dump custom-format archive.
PG_CUSTOM_MAGIC: Final[bytes] = b"PGDMP"


class PostgresDumpError(RuntimeError):
    """The dump file is missing, empty, or not a custom-format archive."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def check_dump(path: Path) -> int:
    """Size of a valid custom-format dump; raises ``PostgresDumpError`` otherwise."""
    if not path.is_file():
        raise PostgresDumpError("dump file not found in the backup work directory")
    size = path.stat().st_size
    if size == 0:
        raise PostgresDumpError("dump file is empty")
    with path.open("rb") as handle:
        if handle.read(len(PG_CUSTOM_MAGIC)) != PG_CUSTOM_MAGIC:
            raise PostgresDumpError("dump file is not a pg_dump custom-format archive (-Fc)")
    return size


def backup_postgres(
    store: BackupStore,
    key: BackupKey,
    *,
    work_dir: Path,
    dump_name: str = DUMP_NAME,
    now: Callable[[], datetime] = _utcnow,
) -> BackupMarker:
    """Encrypt and upload ``work_dir/dump_name``, then write the marker.

    The artifact is uploaded before the marker, so a marker never names a missing object.
    The plaintext dump is removed whether or not the upload succeeded.
    """
    dump = work_dir / dump_name
    started = now()
    try:
        dump_bytes = check_dump(dump)
        object_key = store.artifact_key(KIND, run_stamp(started), dump_name + ".rbk")
        uploaded = encrypt_and_upload(store, key, dump, object_key=object_key, work_dir=work_dir)
    finally:
        dump.unlink(missing_ok=True)
    marker = BackupMarker(
        kind=KIND,
        completed_at=now(),
        object_key=uploaded.object_key,
        size_bytes=uploaded.size_bytes,
        sha256=uploaded.sha256,
    )
    store.write_marker(marker)
    logger.info(
        "backup.postgres.completed",
        dump_bytes=dump_bytes,
        size_bytes=uploaded.size_bytes,
        duration_seconds=round((marker.completed_at - started).total_seconds(), 3),
    )
    return marker
