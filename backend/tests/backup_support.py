"""Fakes shared by the backup tests (R08-06): an in-memory S3 client and key helpers."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pydantic import SecretStr

from app.ops.backup.crypto import BackupKey
from app.ops.backup.store import BackupStore

KEY_BYTES = bytes(range(32))
OTHER_KEY_BYTES = bytes(range(32, 64))
BUCKET = "rudix-backups"
PREFIX = "rudix"
# Default LastModified of fake objects: older than any run, so prunable when unreferenced.
OLD = datetime(2000, 1, 1, tzinfo=UTC)


def make_key(material: bytes = KEY_BYTES) -> BackupKey:
    return BackupKey(material)


def write_key_file(path: Path, material: bytes = KEY_BYTES) -> Path:
    path.write_text(base64.b64encode(material).decode() + "\n")
    return path


def _missing(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, operation)


class FakeS3:
    """The subset of the boto3 S3 client the backup code calls."""

    def __init__(self, *, page_size: int = 1000) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.extra: dict[tuple[str, str], dict[str, Any]] = {}
        # LastModified of every object: OLD unless a test sets it (the mirror's prune guard).
        self.modified: dict[tuple[str, str], datetime] = {}
        self.page_size = page_size
        self.calls: list[str] = []
        self.fail_on: set[str] = set()

    def _check(self, operation: str) -> None:
        self.calls.append(operation)
        if operation in self.fail_on:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, operation)

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **extra: Any) -> None:
        self._check("put_object")
        self.objects[(Bucket, Key)] = bytes(Body)
        self.extra[(Bucket, Key)] = extra

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self._check("get_object")
        if (Bucket, Key) not in self.objects:
            raise _missing("GetObject")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def upload_file(
        self,
        *,
        Filename: str,
        Bucket: str,
        Key: str,
        ExtraArgs: dict[str, Any] | None = None,
    ) -> None:
        self._check("upload_file")
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()
        self.extra[(Bucket, Key)] = dict(ExtraArgs or {})

    def download_file(self, *, Bucket: str, Key: str, Filename: str) -> None:
        self._check("download_file")
        if (Bucket, Key) not in self.objects:
            raise _missing("HeadObject")
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self._check("delete_object")
        self.objects.pop((Bucket, Key), None)

    def list_objects_v2(
        self,
        *,
        Bucket: str,
        Prefix: str = "",
        ContinuationToken: str | None = None,
    ) -> dict[str, Any]:
        self._check("list_objects_v2")
        keys = sorted(
            key for bucket, key in self.objects if bucket == Bucket and key.startswith(Prefix)
        )
        start = int(ContinuationToken or 0)
        page = keys[start : start + self.page_size]
        contents = [
            {
                "Key": key,
                "ETag": '"' + hashlib.md5(self.objects[(Bucket, key)]).hexdigest() + '"',
                "Size": len(self.objects[(Bucket, key)]),
                "LastModified": self.modified.get((Bucket, key), OLD),
            }
            for key in page
        ]
        response: dict[str, Any] = {"Contents": contents, "IsTruncated": False}
        if start + self.page_size < len(keys):
            response["IsTruncated"] = True
            response["NextContinuationToken"] = str(start + self.page_size)
        return response

    def keys(self, bucket: str = BUCKET) -> list[str]:
        return sorted(key for name, key in self.objects if name == bucket)


def make_store(client: FakeS3 | None = None, **kwargs: Any) -> BackupStore:
    return BackupStore(client or FakeS3(), bucket=BUCKET, prefix=PREFIX, **kwargs)


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
NOW = datetime(2026, 11, 28, 3, 15, tzinfo=UTC)
DUMP = b"PGDMP" + bytes(range(200)) * 3


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"script_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backup_config(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "backup_enabled": True,
        "backup_bucket": BUCKET,
        "backup_prefix": PREFIX,
        "backup_s3_sse": "AES256",
        "backup_s3_kms_key_id": None,
        "backup_s3_endpoint": None,
        "backup_s3_region": "eu-central-1",
        "backup_s3_access_key": None,
        "backup_s3_secret_key": None,
        "backup_encryption_key_file": write_key_file(tmp_path / "backup.key"),
        "backup_work_dir": tmp_path / "work",
        "backup_kinds": ["postgres", "qdrant", "objects"],
        "backup_max_age_hours": 26,
        "dependency_connect_timeout_seconds": 2.0,
        "dependency_read_timeout_seconds": 5.0,
        "qdrant_url": "http://qdrant:6333",
        "qdrant_api_key": SecretStr("qdrant-api-key"),
        "qdrant_collection": "documents",
        "backup_qdrant_timeout_seconds": 1800,
        "minio_bucket": "documents",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeQdrant:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.created: list[str] = []
        self.deleted: list[tuple[str, str]] = []

    def get_collections(self) -> Any:
        return SimpleNamespace(collections=[SimpleNamespace(name=name) for name in self.names])

    def get_aliases(self) -> Any:
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name="documents_live", collection_name="documents_te3_v2"),
                SimpleNamespace(alias_name="other", collection_name="unrelated"),
            ]
        )

    def create_snapshot(self, *, collection_name: str, wait: bool) -> Any:
        assert wait is True
        self.created.append(collection_name)
        return SimpleNamespace(name=f"{collection_name}-snap.snapshot")

    def delete_snapshot(self, *, collection_name: str, snapshot_name: str, wait: bool) -> None:
        self.deleted.append((collection_name, snapshot_name))


def snapshot_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        collection = request.url.path.split("/")[2]
        return httpx.Response(200, content=f"snapshot-of-{collection}".encode() * 100)

    return httpx.MockTransport(handler)


def source_bucket(objects: dict[str, bytes]) -> FakeS3:
    source = FakeS3(page_size=2)
    for key, body in objects.items():
        source.objects[("documents", key)] = body
    return source
