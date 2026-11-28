"""Entry point shared by ``scripts/backup_run.py`` and ``scripts/backup_restore.py``.

Builds the store, the key, and the per-kind clients from settings (each injectable for
tests) and dispatches to the kind's module. Kinds: ``postgres`` (encrypts the pg_dump file
in ``BACKUP_WORK_DIR``), ``qdrant`` (snapshots), ``objects`` (bucket mirror).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import httpx

from app.ops.backup import objects as objects_backup
from app.ops.backup import postgres as postgres_backup
from app.ops.backup import qdrant as qdrant_backup
from app.ops.backup.crypto import BackupKey, load_key
from app.ops.backup.markers import BackupMarker
from app.ops.backup.store import BackupConfigurationError, BackupStore

RUN_KINDS: Final[tuple[str, ...]] = ("postgres", "qdrant", "objects")


def configured_key(config: Any) -> BackupKey:
    path = config.backup_encryption_key_file
    if path is None:
        raise BackupConfigurationError("BACKUP_ENCRYPTION_KEY_FILE is not set")
    return load_key(Path(path))


def restore_keys(config: Any, extra_key_files: Sequence[Path] = ()) -> list[BackupKey]:
    """The configured key (when set) followed by older keys kept for restore."""
    keys: list[BackupKey] = []
    if config.backup_encryption_key_file is not None:
        keys.append(configured_key(config))
    keys.extend(load_key(path) for path in extra_key_files)
    if not keys:
        raise BackupConfigurationError("no backup key: set BACKUP_ENCRYPTION_KEY_FILE")
    return keys


def run_backup(
    kind: str,
    config: Any,
    *,
    store: BackupStore | None = None,
    key: BackupKey | None = None,
    qdrant_client: Any | None = None,
    http: httpx.Client | None = None,
    source_client: Any | None = None,
) -> BackupMarker:
    if kind not in RUN_KINDS:
        raise BackupConfigurationError(f"unknown backup kind {kind!r}")
    store = store or BackupStore.from_settings(config)
    key = key or configured_key(config)
    work_dir = Path(config.backup_work_dir)
    if kind == "postgres":
        return postgres_backup.backup_postgres(store, key, work_dir=work_dir)
    if kind == "qdrant":
        return _run_qdrant(config, store, key, work_dir, qdrant_client, http)
    if source_client is None:
        from app.clients.factory import create_minio_client

        source_client = create_minio_client(config)
    marker, _ = objects_backup.mirror_objects(
        store,
        key,
        source_client=source_client,
        source_bucket=config.minio_bucket,
        work_dir=work_dir / "objects",
    )
    return marker


def _run_qdrant(
    config: Any,
    store: BackupStore,
    key: BackupKey,
    work_dir: Path,
    qdrant_client: Any | None,
    http: httpx.Client | None,
) -> BackupMarker:
    if qdrant_client is None:
        from app.clients.factory import create_qdrant_client

        # A snapshot with wait=True blocks until it is written: the request-path
        # QDRANT_TIMEOUT_SECONDS (2 s by default) would abort it on any real collection.
        qdrant_client = create_qdrant_client(
            config, timeout_seconds=config.backup_qdrant_timeout_seconds
        )
    api_key = config.qdrant_api_key.get_secret_value() if config.qdrant_api_key else None
    owned_http = http is None
    client = http or httpx.Client()
    try:
        return qdrant_backup.backup_qdrant(
            store,
            key,
            client=qdrant_client,
            http=client,
            qdrant_url=str(config.qdrant_url),
            api_key=api_key,
            base_collection=config.qdrant_collection,
            work_dir=work_dir / "qdrant",
        )
    finally:
        if owned_http:
            client.close()
