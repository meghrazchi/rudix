"""Download and decrypt backups for a restore or a drill (R08-06, R08-04).

Every artifact's SHA-256 is checked against the marker or the run manifest before it is
decrypted, and decryption authenticates every chunk, so a corrupted or tampered backup
fails here instead of half-way through ``pg_restore``. Output files are created with mode
0600; plaintext never leaves the output path the operator chose.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger
from app.ops.backup import objects as objects_backup
from app.ops.backup import qdrant as qdrant_backup
from app.ops.backup.crypto import BackupKey, decrypt_file, sha256_file
from app.ops.backup.markers import BackupMarker, kind_prefix
from app.ops.backup.store import BackupStore, download_and_decrypt_bytes

logger = get_logger("ops.backup.restore")


class RestoreError(RuntimeError):
    """A marker is missing, an object key is outside the prefix, or a hash differs."""


@dataclass(slots=True)
class RestoreResult:
    kind: str
    object_key: str
    files: list[Path] = field(default_factory=list)
    plaintext_bytes: int = 0


def resolve_object_key(store: BackupStore, kind: str, object_key: str | None) -> BackupMarker | str:
    """The latest marker when ``object_key`` is None, else the given key (checked)."""
    if object_key is None:
        marker = store.read_marker(kind)
        if marker is None:
            raise RestoreError(f"no {kind} marker in the backup bucket")
        return marker
    if not object_key.startswith(kind_prefix(store.prefix, kind)) or ".." in object_key:
        raise RestoreError(f"object key is outside the {kind} prefix")
    return object_key


def _fetch(
    store: BackupStore,
    keys: Sequence[BackupKey],
    object_key: str,
    destination: Path,
    *,
    expected_sha256: str | None,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    encrypted = destination.with_name(destination.name + ".rbk.download")
    try:
        store.download_file(object_key, encrypted)
        if expected_sha256 is not None and sha256_file(encrypted) != expected_sha256:
            raise RestoreError("downloaded backup does not match its recorded SHA-256")
        return decrypt_file(encrypted, destination, keys).plaintext_bytes
    finally:
        encrypted.unlink(missing_ok=True)


def restore_file(
    store: BackupStore,
    keys: Sequence[BackupKey],
    *,
    kind: str,
    object_key: str | None,
    out: Path,
) -> RestoreResult:
    """Single-file kinds (``postgres``, ``neo4j``): download and decrypt to ``out``."""
    target = resolve_object_key(store, kind, object_key)
    key_name = target.object_key if isinstance(target, BackupMarker) else target
    expected = target.sha256 if isinstance(target, BackupMarker) else None
    size = _fetch(store, keys, key_name, out, expected_sha256=expected)
    logger.info("backup.restore.file_done", kind=kind, plaintext_bytes=size)
    return RestoreResult(kind=kind, object_key=key_name, files=[out], plaintext_bytes=size)


def _manifest(
    store: BackupStore, keys: Sequence[BackupKey], kind: str, object_key: str | None, work: Path
) -> tuple[str, bytes]:
    target = resolve_object_key(store, kind, object_key)
    key_name = target.object_key if isinstance(target, BackupMarker) else target
    raw = download_and_decrypt_bytes(store, list(keys), key_name, work_dir=work)
    return key_name, raw


def restore_qdrant(
    store: BackupStore, keys: Sequence[BackupKey], *, object_key: str | None, out_dir: Path
) -> RestoreResult:
    """Every collection snapshot of a run into ``out_dir``, plus ``aliases.json``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    key_name, raw = _manifest(store, keys, qdrant_backup.KIND, object_key, out_dir)
    manifest = qdrant_backup.parse_manifest(raw)
    result = RestoreResult(kind=qdrant_backup.KIND, object_key=key_name)
    for entry in manifest["collections"]:
        name = str(entry["name"])
        if "/" in name or name.startswith("."):
            raise RestoreError("collection name in the manifest is not a plain name")
        destination = out_dir / f"{name}.snapshot"
        result.plaintext_bytes += _fetch(
            store, keys, str(entry["object_key"]), destination, expected_sha256=entry["sha256"]
        )
        result.files.append(destination)
    aliases = out_dir / "aliases.json"
    aliases.write_text(json.dumps(manifest.get("aliases") or [], indent=2, sort_keys=True))
    result.files.append(aliases)
    logger.info("backup.restore.qdrant_done", collections=len(manifest["collections"]))
    return result


def restore_objects(
    store: BackupStore, keys: Sequence[BackupKey], *, object_key: str | None, out_dir: Path
) -> RestoreResult:
    """Every mirrored object of a manifest into ``out_dir/<source key>``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    key_name, raw = _manifest(store, keys, objects_backup.KIND, object_key, out_dir)
    manifest = objects_backup.parse_manifest(raw)
    result = RestoreResult(kind=objects_backup.KIND, object_key=key_name)
    for source_key, entry in sorted(manifest["objects"].items()):
        destination = out_dir / objects_backup.safe_relative_path(source_key)
        result.plaintext_bytes += _fetch(
            store, keys, str(entry["backup_key"]), destination, expected_sha256=entry["sha256"]
        )
        result.files.append(destination)
    logger.info("backup.restore.objects_done", objects=len(result.files))
    return result
