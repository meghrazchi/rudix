"""The backup bucket: an S3 client built from the ``BACKUP_*`` settings (R08-06).

The bucket should live in another account or region than the application data, with
versioning and object lock or a retention policy (docs/runbooks/BACKUP_AND_RESTORE.md).
Every upload asks for server-side encryption (``BACKUP_S3_SSE``) on top of the client-side
encryption every artifact already has.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.core.logging import get_logger
from app.ops.backup.crypto import BackupKey, decrypt_file, encrypt_file
from app.ops.backup.markers import BackupMarker, kind_prefix, marker_key

logger = get_logger("ops.backup.store")

_MISSING_CODES: Final[frozenset[str]] = frozenset({"404", "NoSuchKey", "NotFound"})


class BackupConfigurationError(RuntimeError):
    """Backups are disabled or a required setting is missing."""


def sse_extra_args(sse: str, kms_key_id: str | None) -> dict[str, str]:
    """``ExtraArgs`` / ``put_object`` arguments for the configured server-side encryption."""
    if sse == "none":
        return {}
    args = {"ServerSideEncryption": sse}
    if sse == "aws:kms" and kms_key_id:
        args["SSEKMSKeyId"] = kms_key_id
    return args


def build_backup_s3_client(config: Any) -> Any:
    """boto3 S3 client for the backup bucket; path-style addressing when an endpoint is set."""
    endpoint = config.backup_s3_endpoint
    access_key = config.backup_s3_access_key
    secret_key = config.backup_s3_secret_key
    s3_options = {"addressing_style": "path"} if endpoint is not None else {}
    return boto3.client(
        "s3",
        endpoint_url=str(endpoint) if endpoint is not None else None,
        region_name=config.backup_s3_region,
        aws_access_key_id=access_key.get_secret_value() if access_key else None,
        aws_secret_access_key=secret_key.get_secret_value() if secret_key else None,
        config=Config(
            connect_timeout=config.dependency_connect_timeout_seconds,
            read_timeout=max(60.0, float(config.dependency_read_timeout_seconds)),
            retries={"mode": "standard", "total_max_attempts": 5},
            s3=s3_options,
        ),
    )


def is_missing(exc: Exception) -> bool:
    if not isinstance(exc, ClientError):
        return False
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code in _MISSING_CODES


class BackupStore:
    """Reads and writes artifacts and markers under ``<bucket>/<prefix>/``."""

    def __init__(
        self,
        client: Any,
        *,
        bucket: str,
        prefix: str,
        sse: str = "AES256",
        kms_key_id: str | None = None,
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._sse_args = sse_extra_args(sse, kms_key_id)

    @classmethod
    def from_settings(
        cls, config: Any, *, client: Any | None = None, require_enabled: bool = True
    ) -> BackupStore:
        """Store for the configured bucket. The freshness check passes
        ``require_enabled=False``: it only reads markers, on hosts that never run backups."""
        if require_enabled and not config.backup_enabled:
            raise BackupConfigurationError("backups are disabled (BACKUP_ENABLED=false)")
        if not config.backup_bucket:
            raise BackupConfigurationError("BACKUP_BUCKET is not set")
        return cls(
            client if client is not None else build_backup_s3_client(config),
            bucket=config.backup_bucket,
            prefix=config.backup_prefix,
            sse=config.backup_s3_sse,
            kms_key_id=config.backup_s3_kms_key_id,
        )

    @property
    def sse_args(self) -> dict[str, str]:
        return dict(self._sse_args)

    def artifact_key(self, kind: str, stamp: str, name: str) -> str:
        return f"{kind_prefix(self.prefix, kind)}{stamp}/{name}"

    def upload_file(self, path: Path, key: str) -> None:
        self.client.upload_file(
            Filename=str(path), Bucket=self.bucket, Key=key, ExtraArgs=self.sse_args
        )

    def put_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **self._sse_args
        )

    def get_bytes(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if is_missing(exc):
                return None
            raise
        body = response["Body"]
        try:
            return bytes(body.read())
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def download_file(self, key: str, path: Path) -> None:
        self.client.download_file(Bucket=self.bucket, Key=key, Filename=str(path))

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def write_marker(self, marker: BackupMarker) -> None:
        marker.validate(self.prefix)
        self.put_bytes(
            marker_key(self.prefix, marker.kind),
            marker.to_json(),
            content_type="application/json",
        )
        logger.info(
            "backup.marker.written",
            kind=marker.kind,
            size_bytes=marker.size_bytes,
            completed_at=marker.to_dict()["completed_at"],
        )

    def read_marker(self, kind: str) -> BackupMarker | None:
        raw = self.get_bytes(marker_key(self.prefix, kind))
        if raw is None:
            return None
        return BackupMarker.from_json(raw, prefix=self.prefix)


@dataclass(frozen=True, slots=True)
class UploadedArtifact:
    object_key: str
    size_bytes: int
    sha256: str
    plaintext_bytes: int


def encrypt_and_upload(
    store: BackupStore, key: BackupKey, source: Path, *, object_key: str, work_dir: Path
) -> UploadedArtifact:
    """Encrypt ``source`` into ``work_dir``, upload it, and remove the ciphertext copy."""
    work_dir.mkdir(parents=True, exist_ok=True)
    encrypted = work_dir / (source.name + ".rbk.tmp")
    try:
        result = encrypt_file(source, encrypted, key)
        store.upload_file(encrypted, object_key)
    finally:
        encrypted.unlink(missing_ok=True)
    return UploadedArtifact(
        object_key=object_key,
        size_bytes=result.ciphertext_bytes,
        sha256=result.sha256,
        plaintext_bytes=result.plaintext_bytes,
    )


def encrypt_bytes_and_upload(
    store: BackupStore, key: BackupKey, data: bytes, *, name: str, object_key: str, work_dir: Path
) -> UploadedArtifact:
    """Same as ``encrypt_and_upload`` for a small in-memory document (a run manifest)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    plain = work_dir / (name + ".plain.tmp")
    try:
        fd = os.open(plain, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        return encrypt_and_upload(store, key, plain, object_key=object_key, work_dir=work_dir)
    finally:
        plain.unlink(missing_ok=True)


def download_and_decrypt_bytes(
    store: BackupStore, keys: list[BackupKey], object_key: str, *, work_dir: Path
) -> bytes:
    """Download a small encrypted document (a run manifest) and return its plaintext."""
    work_dir.mkdir(parents=True, exist_ok=True)
    name = object_key.rsplit("/", 1)[-1]
    encrypted = work_dir / (name + ".download.tmp")
    plain = work_dir / (name + ".plain.tmp")
    try:
        store.download_file(object_key, encrypted)
        decrypt_file(encrypted, plain, keys)
        return plain.read_bytes()
    finally:
        encrypted.unlink(missing_ok=True)
        plain.unlink(missing_ok=True)
