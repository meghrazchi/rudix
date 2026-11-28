"""Backup, freshness, and restore settings (0.8.0, R08-06).

Owned by A2. Backups stay off by default (``BACKUP_ENABLED=false``) and the deploy gate keeps
its SSH mode (``DEPLOY_BACKUP_GATE`` is a release-workflow variable, not a setting). The
runner (``scripts/backup_run.py``) encrypts every artifact client-side with AES-256-GCM
(``app/ops/backup/crypto.py``) before it reaches the backup bucket, and writes one marker per
kind (``<prefix>/<kind>/latest.json``, contract 5.2.9) that the freshness check reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import NoDecode

# Kinds the runner produces. ``neo4j`` has a marker only when an operator backup writes one
# (Neo4j Community cannot dump online), so it is never in the default list.
BACKUP_KIND_NAMES: Final[frozenset[str]] = frozenset({"postgres", "qdrant", "objects", "neo4j"})

BackupS3Sse = Literal["AES256", "aws:kms", "none"]


class BackupSettings(BaseModel):
    """Backup bucket, encryption, and freshness settings."""

    # Master switch of the runner and the restore tool. False: both refuse to run.
    backup_enabled: bool = False
    # S3-compatible endpoint of the backup bucket. None uses the AWS default endpoint for
    # the region; a set endpoint (MinIO, another provider) switches to path-style addressing.
    backup_s3_endpoint: AnyHttpUrl | None = None
    backup_s3_region: str | None = Field(default=None, min_length=1, max_length=64)
    # Credentials of the backup bucket only (write and read, no delete when the provider
    # allows it). None falls back to the default AWS credential chain (instance role).
    backup_s3_access_key: SecretStr | None = None
    backup_s3_secret_key: SecretStr | None = None
    backup_bucket: str | None = Field(default=None, min_length=3, max_length=63)
    backup_prefix: str = Field(
        default="rudix", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
    )
    # Server-side encryption requested on every upload, on top of client-side encryption.
    backup_s3_sse: BackupS3Sse = "AES256"
    backup_s3_kms_key_id: str | None = Field(default=None, min_length=1, max_length=2048)
    # ``none`` is refused in staging and production unless this is true (for a provider or
    # a MinIO without a KMS that rejects SSE headers). Client-side encryption still applies.
    backup_s3_sse_none_allowed: bool = False
    # File holding the base64 of 32 random bytes (``openssl rand -base64 32``). Required when
    # backups are enabled; mounted from a secret, never logged, never written to a marker.
    backup_encryption_key_file: Path | None = None
    # Working directory of the runner: the pg_dump output and temporary ciphertext.
    backup_work_dir: Path = Path("/tmp/rudix-backup")
    # A kind whose marker is older than this is stale (same value as the release workflow's
    # DEPLOY_BACKUP_MAX_AGE_HOURS default).
    backup_max_age_hours: int = Field(default=26, ge=1, le=24 * 30)
    # Beat task ``ops.backups.check_freshness``: reads the markers and exports their age
    # (``rudix_backup_last_success_timestamp_seconds``). Off: the task is a no-op.
    backup_freshness_check_enabled: bool = False
    backup_freshness_interval_seconds: int = Field(default=900, ge=60, le=86_400)
    # Kinds the freshness check and ``scripts/check_backup_freshness.py`` require.
    backup_kinds: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["postgres", "qdrant", "objects"]
    )

    @field_validator("backup_kinds", mode="before")
    @classmethod
    def _parse_backup_kinds(cls, value: Any) -> list[str]:
        raw_items = value.split(",") if isinstance(value, str) else value
        if not isinstance(raw_items, list | tuple | set | frozenset):
            raise ValueError("backup_kinds must be a comma list or list")
        kinds: list[str] = []
        for item in raw_items:
            kind = str(item).strip().lower()
            if not kind:
                continue
            if kind not in BACKUP_KIND_NAMES:
                raise ValueError(f"backup_kinds: unknown kind {kind!r}")
            if kind not in kinds:
                kinds.append(kind)
        return kinds

    @field_validator("backup_prefix", mode="before")
    @classmethod
    def _strip_prefix(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip().strip("/")
        if not stripped or ".." in stripped.split("/") or "//" in stripped:
            raise ValueError("backup_prefix must be a relative key prefix")
        return stripped

    @model_validator(mode="after")
    def _validate_backup_settings(self) -> BackupSettings:
        if not self.backup_enabled:
            return self
        environment = str(getattr(getattr(self, "environment", None), "value", "") or "")
        if environment not in {"staging", "production"}:
            return self
        if not self.backup_bucket:
            raise ValueError("backup_bucket is required when backup_enabled in staging/production")
        if self.backup_encryption_key_file is None:
            raise ValueError(
                "backup_encryption_key_file is required when backup_enabled in staging/production"
            )
        if self.backup_s3_sse == "none" and not self.backup_s3_sse_none_allowed:
            raise ValueError(
                "backup_s3_sse=none needs backup_s3_sse_none_allowed=true in staging/production"
            )
        return self
