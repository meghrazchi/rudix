"""Qdrant backup: one snapshot per collection, encrypted and uploaded (R08-06).

For every collection of this deployment (``QDRANT_COLLECTION`` and its alias generations
``QDRANT_COLLECTION_*``, R06-08) the runner asks Qdrant for a snapshot through the existing
client factory, downloads it over HTTP (``api-key`` header, streamed to disk), encrypts it,
uploads it, and deletes the snapshot from the server. An encrypted run manifest lists the
collections, their objects, and the aliases; the ``qdrant`` marker points at it.

Qdrant is rebuildable from PostgreSQL chunks and the embedding cache
(docs/runbooks/DR_VECTOR_INDEX_LOSS.md); a snapshot restore is the faster path.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

import httpx

from app.core.logging import get_logger
from app.ops.backup.crypto import BackupKey
from app.ops.backup.markers import BackupMarker, run_stamp
from app.ops.backup.store import BackupStore, encrypt_and_upload, encrypt_bytes_and_upload

logger = get_logger("ops.backup.qdrant")

KIND: Final[str] = "qdrant"
MANIFEST_NAME: Final[str] = "manifest.json"
MANIFEST_VERSION: Final[int] = 1
_DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=600.0)


class QdrantBackupError(RuntimeError):
    """No collection to back up, or Qdrant returned no snapshot."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def deployment_collections(client: Any, base_name: str) -> list[str]:
    """``base_name`` and its generations (``base_name_*``), sorted."""
    names = [item.name for item in client.get_collections().collections]
    return sorted(name for name in names if name == base_name or name.startswith(f"{base_name}_"))


def deployment_aliases(client: Any, collections: list[str]) -> list[dict[str, str]]:
    wanted = set(collections)
    aliases = getattr(client.get_aliases(), "aliases", None) or []
    return sorted(
        (
            {"alias": item.alias_name, "collection": item.collection_name}
            for item in aliases
            if item.collection_name in wanted
        ),
        key=lambda item: item["alias"],
    )


def snapshot_url(qdrant_url: str, collection: str, snapshot: str) -> str:
    base = qdrant_url.rstrip("/")
    return f"{base}/collections/{quote(collection, safe='')}/snapshots/{quote(snapshot, safe='')}"


def download_snapshot(
    http: httpx.Client, url: str, destination: Path, *, api_key: str | None
) -> int:
    """Stream one snapshot to ``destination``; returns its size."""
    headers = {"api-key": api_key} if api_key else {}
    size = 0
    with http.stream("GET", url, headers=headers, timeout=_DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for block in response.iter_bytes():
                handle.write(block)
                size += len(block)
    return size


def _backup_collection(
    *,
    client: Any,
    http: httpx.Client,
    store: BackupStore,
    key: BackupKey,
    qdrant_url: str,
    api_key: str | None,
    collection: str,
    stamp: str,
    work_dir: Path,
) -> dict[str, Any]:
    snapshot = client.create_snapshot(collection_name=collection, wait=True)
    if snapshot is None or not getattr(snapshot, "name", None):
        raise QdrantBackupError(f"Qdrant returned no snapshot for collection {collection}")
    local = work_dir / f"{collection}.snapshot"
    try:
        snapshot_bytes = download_snapshot(
            http, snapshot_url(qdrant_url, collection, snapshot.name), local, api_key=api_key
        )
        uploaded = encrypt_and_upload(
            store,
            key,
            local,
            object_key=store.artifact_key(KIND, stamp, f"{collection}.snapshot.rbk"),
            work_dir=work_dir,
        )
    finally:
        local.unlink(missing_ok=True)
        try:
            client.delete_snapshot(
                collection_name=collection, snapshot_name=snapshot.name, wait=True
            )
        except Exception as exc:  # the backup stands; a leftover snapshot only costs disk
            logger.warning(
                "backup.qdrant.snapshot_delete_failed",
                collection=collection,
                error=type(exc).__name__,
            )
    logger.info(
        "backup.qdrant.collection_done",
        collection=collection,
        snapshot_bytes=snapshot_bytes,
        size_bytes=uploaded.size_bytes,
    )
    return {
        "name": collection,
        "object_key": uploaded.object_key,
        "size_bytes": uploaded.size_bytes,
        "sha256": uploaded.sha256,
        "snapshot_bytes": snapshot_bytes,
    }


def backup_qdrant(
    store: BackupStore,
    key: BackupKey,
    *,
    client: Any,
    http: httpx.Client,
    qdrant_url: str,
    api_key: str | None,
    base_collection: str,
    work_dir: Path,
    now: Callable[[], datetime] = _utcnow,
) -> BackupMarker:
    """Snapshot, encrypt, and upload every collection of the deployment, then the marker."""
    started = now()
    stamp = run_stamp(started)
    collections = deployment_collections(client, base_collection)
    if not collections:
        raise QdrantBackupError("no Qdrant collection of this deployment exists")
    aliases = deployment_aliases(client, collections)
    work_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        _backup_collection(
            client=client,
            http=http,
            store=store,
            key=key,
            qdrant_url=qdrant_url,
            api_key=api_key,
            collection=name,
            stamp=stamp,
            work_dir=work_dir,
        )
        for name in collections
    ]
    manifest = {
        "format_version": MANIFEST_VERSION,
        "kind": KIND,
        "created_at": started.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "collections": entries,
        "aliases": aliases,
    }
    uploaded = encrypt_bytes_and_upload(
        store,
        key,
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
        name=MANIFEST_NAME,
        object_key=store.artifact_key(KIND, stamp, f"{MANIFEST_NAME}.rbk"),
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
    logger.info(
        "backup.qdrant.completed",
        collections=len(entries),
        aliases=len(aliases),
        duration_seconds=round((marker.completed_at - started).total_seconds(), 3),
    )
    return marker


def parse_manifest(raw: bytes) -> dict[str, Any]:
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("kind") != KIND:
        raise QdrantBackupError("not a Qdrant backup manifest")
    if not isinstance(manifest.get("collections"), list):
        raise QdrantBackupError("Qdrant backup manifest has no collection list")
    return manifest
