"""Object storage backup: incremental, encrypted mirror of the app bucket (R08-06).

For managed S3-compatible storage, provider replication to another region plus bucket
versioning is preferred (docs/runbooks/BACKUP_AND_RESTORE.md); this mirror is for
self-hosted MinIO and providers without replication.

Each run lists the application bucket (``MINIO_BUCKET``) and copies only objects whose ETag
or size changed since the previous run, according to the previous run's manifest. Every copy
is encrypted client-side and stored under ``<prefix>/objects/data/<sha256 of the source
key>.rbk``, so the backup bucket's listing reveals no object names. The new manifest
(source key, ETag, size, backup key, ciphertext hash) is itself encrypted and the
``objects`` marker points at it.

Objects removed from the application bucket are removed from the mirror in the same run, so
data deletion (F143) reaches the backup; the backup bucket's versioning and noncurrent-version
expiry decide how long a removed copy stays recoverable. A source listing that comes back
empty while the previous manifest is not is treated as an error, never as "delete all".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.core.logging import get_logger
from app.ops.backup.crypto import BackupKey, BackupWrongKeyError
from app.ops.backup.markers import BackupMarker, kind_prefix, run_stamp
from app.ops.backup.store import (
    BackupStore,
    download_and_decrypt_bytes,
    encrypt_and_upload,
    encrypt_bytes_and_upload,
)

logger = get_logger("ops.backup.objects")

KIND: Final[str] = "objects"
MANIFEST_NAME: Final[str] = "manifest.json"
MANIFEST_VERSION: Final[int] = 1


class ObjectMirrorError(RuntimeError):
    """The mirror refused to run (for example an empty source listing)."""


@dataclass(frozen=True, slots=True)
class SourceObject:
    key: str
    etag: str
    size: int


@dataclass(frozen=True, slots=True)
class MirrorStats:
    copied: int
    unchanged: int
    removed: int
    total: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


def list_source_objects(client: Any, bucket: str) -> Iterator[SourceObject]:
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for item in page.get("Contents") or []:
            yield SourceObject(
                key=str(item["Key"]),
                etag=str(item.get("ETag", "")).strip('"'),
                size=int(item.get("Size", 0)),
            )
        if not page.get("IsTruncated"):
            return
        token = page.get("NextContinuationToken")
        if not token:
            return


def mirror_key(store: BackupStore, source_key: str) -> str:
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    return f"{kind_prefix(store.prefix, KIND)}data/{digest}.rbk"


def load_previous_manifest(
    store: BackupStore, keys: list[BackupKey], *, work_dir: Path
) -> dict[str, dict[str, Any]]:
    marker = store.read_marker(KIND)
    if marker is None:
        return {}
    raw = download_and_decrypt_bytes(store, keys, marker.object_key, work_dir=work_dir)
    objects: dict[str, dict[str, Any]] = parse_manifest(raw)["objects"]
    return objects


def parse_manifest(raw: bytes) -> dict[str, Any]:
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("kind") != KIND:
        raise ObjectMirrorError("not an object backup manifest")
    if not isinstance(manifest.get("objects"), dict):
        raise ObjectMirrorError("object backup manifest has no object map")
    return manifest


def _copy_one(
    *,
    source_client: Any,
    source_bucket: str,
    store: BackupStore,
    key: BackupKey,
    item: SourceObject,
    work_dir: Path,
) -> dict[str, Any]:
    local = work_dir / f"object-{hashlib.sha256(item.key.encode()).hexdigest()[:16]}"
    try:
        source_client.download_file(Bucket=source_bucket, Key=item.key, Filename=str(local))
        uploaded = encrypt_and_upload(
            store, key, local, object_key=mirror_key(store, item.key), work_dir=work_dir
        )
    finally:
        local.unlink(missing_ok=True)
    return {
        "etag": item.etag,
        "size": item.size,
        "backup_key": uploaded.object_key,
        "sha256": uploaded.sha256,
    }


def mirror_objects(
    store: BackupStore,
    key: BackupKey,
    *,
    source_client: Any,
    source_bucket: str,
    work_dir: Path,
    restore_keys: list[BackupKey] | None = None,
    now: Callable[[], datetime] = _utcnow,
) -> tuple[BackupMarker, MirrorStats]:
    """Copy new and changed objects, drop removed ones, write manifest and marker."""
    started = now()
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        previous = load_previous_manifest(store, restore_keys or [key], work_dir=work_dir)
    except BackupWrongKeyError:
        # After a key rotation without the old key: copy everything again (documented).
        logger.warning("backup.objects.previous_manifest_unreadable", reason="key_rotated")
        previous = {}
    current: dict[str, dict[str, Any]] = {}
    copied = unchanged = 0
    for item in list_source_objects(source_client, source_bucket):
        entry = previous.get(item.key)
        if entry and entry.get("etag") == item.etag and entry.get("size") == item.size:
            current[item.key] = entry
            unchanged += 1
            continue
        current[item.key] = _copy_one(
            source_client=source_client,
            source_bucket=source_bucket,
            store=store,
            key=key,
            item=item,
            work_dir=work_dir,
        )
        copied += 1
    if not current and previous:
        raise ObjectMirrorError(
            "source bucket listed no objects while the previous manifest has some; "
            "refusing to remove the mirror"
        )
    removed_keys = sorted(set(previous) - set(current))
    manifest = {
        "format_version": MANIFEST_VERSION,
        "kind": KIND,
        "created_at": started.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "objects": current,
    }
    uploaded = encrypt_bytes_and_upload(
        store,
        key,
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
        name=MANIFEST_NAME,
        object_key=store.artifact_key(KIND, run_stamp(started), f"{MANIFEST_NAME}.rbk"),
        work_dir=work_dir,
    )
    marker = BackupMarker(
        kind=KIND,
        completed_at=now(),
        object_key=uploaded.object_key,
        size_bytes=uploaded.size_bytes,
        sha256=uploaded.sha256,
    )
    store.write_marker(marker)
    # Removed only after the new manifest and marker no longer reference them.
    for source_key in removed_keys:
        backup_key = str(previous[source_key].get("backup_key", ""))
        if backup_key.startswith(f"{kind_prefix(store.prefix, KIND)}data/"):
            store.delete(backup_key)
    stats = MirrorStats(
        copied=copied, unchanged=unchanged, removed=len(removed_keys), total=len(current)
    )
    logger.info(
        "backup.objects.completed",
        copied=stats.copied,
        unchanged=stats.unchanged,
        removed=stats.removed,
        total=stats.total,
        duration_seconds=round((marker.completed_at - started).total_seconds(), 3),
    )
    return marker, stats


def safe_relative_path(source_key: str) -> Path:
    """Local restore path for a source key; refuses absolute paths and parent references."""
    parts = [part for part in source_key.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts) or source_key.startswith("/"):
        raise ObjectMirrorError("object key cannot be restored to a local path")
    return Path(*parts)
