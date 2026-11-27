"""Qdrant, MinIO, upload security (malware, DLP, duplicates), and OCR settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    SecretStr,
    field_validator,
)

from app.core.settings.enums import (
    Environment,
    QdrantDistance,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class StorageSettings(BaseModel):
    qdrant_url: AnyHttpUrl
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = Field(min_length=2, max_length=128)
    qdrant_vector_size: int = Field(default=1536, ge=8, le=8192)
    qdrant_distance: QdrantDistance = QdrantDistance.cosine
    qdrant_timeout_seconds: float = Field(default=2.0, ge=0.1, le=60.0)
    qdrant_bootstrap_collection: bool = True
    minio_endpoint: AnyHttpUrl
    minio_access_key: str = Field(min_length=1, max_length=128)
    minio_secret_key: SecretStr
    minio_bucket: str = Field(min_length=3, max_length=63)
    minio_bootstrap_bucket: bool = True
    max_upload_size_mb: int = Field(default=25, ge=1, le=512)
    malware_scan_enabled: bool = True
    malware_scan_required: bool = False
    malware_scan_bypass_on_unavailable: bool = False
    malware_scan_clamav_host: str = Field(default="localhost", min_length=1, max_length=255)
    malware_scan_clamav_port: int = Field(default=3310, ge=1, le=65535)
    malware_scan_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    malware_scan_max_bytes: int | None = Field(default=None, ge=1, le=536_870_912)
    malware_scan_stream_chunk_size_bytes: int = Field(default=65_536, ge=1024, le=4_194_304)
    duplicate_detection_enabled: bool = True
    duplicate_detection_action: str = Field(
        default="warn",
        pattern=r"^(allow|warn|reject)$",
    )
    dlp_enabled: bool = True
    dlp_action: str = Field(
        default="warn",
        pattern=r"^(allow|warn|quarantine|reject)$",
    )
    dlp_min_findings: int = Field(default=3, ge=1, le=1000)
    ocr_enabled: bool = True
    ocr_default_languages: str = Field(default="eng", min_length=1, max_length=255)
    ocr_allowed_languages: str = Field(
        default="eng,ara,fas,spa,fra,deu,ita,por,rus,chi_sim,chi_tra,jpn,kor",
        min_length=3,
        max_length=512,
    )
    ocr_max_pages: int = Field(default=100, ge=1, le=1000)
    ocr_page_timeout_seconds: int = Field(default=60, ge=5, le=300)
    ocr_min_text_chars_per_page: int = Field(default=30, ge=1, le=1000)
    ocr_min_text_chars_document: int = Field(default=300, ge=1, le=10000)
    ocr_image_dpi: int = Field(default=300, ge=72, le=600)

    @field_validator("qdrant_collection")
    @classmethod
    def validate_qdrant_collection(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "qdrant_collection must contain only letters, numbers, underscores, or hyphens"
            )
        return value

    @field_validator("minio_bucket")
    @classmethod
    def validate_minio_bucket(cls, value: str) -> str:
        lowered = value.lower()
        if value != lowered:
            raise ValueError("minio_bucket must be lowercase")
        if ".." in lowered or ".-" in lowered or "-." in lowered:
            raise ValueError("minio_bucket has invalid separator sequence")
        if not lowered.replace("-", "").replace(".", "").isalnum():
            raise ValueError("minio_bucket contains invalid characters")
        return lowered


def validate_upload_security(settings: Settings) -> None:
    if (
        settings.malware_scan_max_bytes is not None
        and settings.malware_scan_max_bytes > settings.max_upload_size_mb * 1024 * 1024
    ):
        raise ValueError("malware_scan_max_bytes must be <= configured upload size limit")

    if settings.malware_scan_required and not settings.malware_scan_enabled:
        raise ValueError("malware_scan_enabled must be true when malware_scan_required is true")

    if (
        settings.environment == Environment.production
        and settings.malware_scan_required
        and settings.malware_scan_bypass_on_unavailable
    ):
        raise ValueError(
            "malware_scan_bypass_on_unavailable must be false in production when scanning is required"
        )

    if (
        settings.environment in {Environment.production, Environment.staging}
        and settings.malware_scan_enabled
        and settings.malware_scan_clamav_host.strip().lower()
        in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    ):
        raise ValueError(
            "malware_scan_clamav_host must point to the ClamAV service in staging/production; "
            "set MALWARE_SCAN_CLAMAV_HOST or set MALWARE_SCAN_ENABLED=false explicitly"
        )
