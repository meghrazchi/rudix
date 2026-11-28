"""Object storage backup: incremental, encrypted mirror of the app bucket (R08-06).

For managed S3-compatible storage, provider replication to another region plus bucket
versioning is preferred (docs/runbooks/BACKUP_AND_RESTORE.md); this mirror is for
self-hosted MinIO and providers without replication.

Each run lists the application bucket (``MINIO_BUCKET``) and copies only objects whose ETag
or size changed since the previous run, according to the previous run's manifest. Every copy
is encrypted client-side and stored under ``<prefix>/objects/data/<sha256 of the source
key>/<hash of ETag, size, and key id>.rbk``, so the backup bucket's listing reveals no object
names, and a changed object or a new key never overwrites a copy that the current marker's
manifest still references: a run that fails half-way leaves the previous backup restorable,
and a retry of the same version writes the same key. The new manifest (source key, ETag,
size, backup key, ciphertext hash) is itself encrypted and the ``objects`` marker points at
it.

After the marker is written, every copy under ``data/`` that the new manifest does not
reference and that is older than the run's start is pruned: objects removed from the
application bucket (data deletion, F143, reaches the backup), superseded versions, and
copies left by a failed run or made with a rotated key. The backup bucket's versioning and
noncurrent-version expiry decide how long a pruned copy stays recoverable. A prune the
credentials may not perform (no delete permission) is logged and leaves the copy. A source
listing that comes back empty while the previous manifest is not is treated as an error,
never as "delete all".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

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
    pruned: int = 0
    prune_failed: int = 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _list_pages(client: Any, bucket: str, prefix: str | None) -> Iterator[dict[str, Any]]:
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if prefix:
            kwargs["Prefix"] = prefix
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        yield from page.get("Contents") or []
        if not page.get("IsTruncated"):
            return
        token = page.get("NextContinuationToken")
        if not token:
            return


def list_source_objects(client: Any, bucket: str) -> Iterator[SourceObject]:
    for item in _list_pages(client, bucket, None):
        yield SourceObject(
            key=str(item["Key"]),
            etag=str(item.get("ETag", "")).strip('"'),
            size=int(item.get("Size", 0)),
        )


def data_prefix(store: BackupStore) -> str:
    return f"{kind_prefix(store.prefix, KIND)}data/"


def mirror_key(store: BackupStore, item: SourceObject, key: BackupKey) -> str:
    """Backup key of one version of a source object under one encryption key."""
    name = hashlib.sha256(item.key.encode("utf-8")).hexdigest()
    version = hashlib.sha256(f"{item.etag}:{item.size}:{key.key_id_hex}".encode()).hexdigest()
    return f"{data_prefix(store)}{name}/{version[:32]}.rbk"


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
            store, key, local, object_key=mirror_key(store, item, key), work_dir=work_dir
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
    # Pruned only after the new manifest and marker no longer reference them.
    keep = {str(entry.get("backup_key", "")) for entry in current.values()}
    # An empty manifest prunes nothing: with an unreadable previous manifest (key rotated)
    # an empty listing must not read as "delete every copy".
    pruned, prune_failed = prune_unreferenced(store, keep, before=started) if keep else (0, 0)
    stats = MirrorStats(
        copied=copied,
        unchanged=unchanged,
        removed=len(removed_keys),
        total=len(current),
        pruned=pruned,
        prune_failed=prune_failed,
    )
    logger.info(
        "backup.objects.completed",
        copied=stats.copied,
        unchanged=stats.unchanged,
        removed=stats.removed,
        total=stats.total,
        pruned=stats.pruned,
        prune_failed=stats.prune_failed,
        duration_seconds=round((marker.completed_at - started).total_seconds(), 3),
    )
    return marker, stats


def _modified_before(item: dict[str, Any], before: datetime) -> bool:
    modified = item.get("LastModified")
    if not isinstance(modified, datetime):
        return False  # unknown age: keep it
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=UTC)
    return modified < before


def prune_unreferenced(store: BackupStore, keep: set[str], *, before: datetime) -> tuple[int, int]:
    """Delete copies under ``data/`` not in ``keep`` and older than ``before``.

    Copies written after ``before`` belong to this or a concurrent run and are kept. A delete
    the credentials may not perform is counted and logged (error code only), never raised:
    the backup itself is complete.
    """
    pruned = failed = 0
    error_code = ""
    for item in list(_list_pages(store.client, store.bucket, data_prefix(store))):
        backup_key = str(item["Key"])
        if backup_key in keep or not _modified_before(item, before):
            continue
        try:
            store.delete(backup_key)
        except ClientError as exc:
            failed += 1
            error_code = str(exc.response.get("Error", {}).get("Code", ""))
            continue
        pruned += 1
    if failed:
        logger.warning("backup.objects.prune_failed", failed=failed, error_code=error_code)
    return pruned, failed


def safe_relative_path(source_key: str) -> Path:
    """Local restore path for a source key; refuses absolute paths and parent references."""
    parts = [part for part in source_key.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts) or source_key.startswith("/"):
        raise ObjectMirrorError("object key cannot be restored to a local path")
    return Path(*parts)
