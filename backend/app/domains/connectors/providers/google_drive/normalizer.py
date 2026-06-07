"""Google Drive API response → NormalizedExternalItem conversion helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.content_hash import hash_dict
from app.domains.connectors.sdk.metadata import build_metadata
from app.models.enums import ExternalItemType, ExternalItemVisibility

_PROVIDER_KEY = "google_drive"
_GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"

GOOGLE_NATIVE_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.spreadsheet",
        "application/vnd.google-apps.presentation",
        "application/vnd.google-apps.drawing",
        "application/vnd.google-apps.form",
        "application/vnd.google-apps.script",
    }
)

# Maps each Google-native MIME type to its preferred export MIME type for ingestion.
NATIVE_EXPORT_MIME: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "application/pdf",
    "application/vnd.google-apps.form": "application/pdf",
    "application/vnd.google-apps.script": "application/json",
}

# MIME types that the ingestion bridge should skip (shortcut/unsupported)
UNSUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/vnd.google-apps.shortcut",
        "application/vnd.google-apps.link",
        "application/vnd.google-apps.unknown",
    }
)


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return datetime.now(UTC)


def is_google_native(mime_type: str | None) -> bool:
    return (mime_type or "") in GOOGLE_NATIVE_MIME_TYPES


def is_google_folder(mime_type: str | None) -> bool:
    return (mime_type or "") == _GOOGLE_FOLDER_MIME


def is_supported_file(mime_type: str | None) -> bool:
    return (mime_type or "") not in UNSUPPORTED_MIME_TYPES


def _file_url(file: dict[str, Any]) -> str:
    url = (file.get("webViewLink") or "").strip()
    if url:
        return url
    file_id = file.get("id", "unknown")
    return f"https://drive.google.com/file/d/{file_id}/view"


def _folder_url(folder: dict[str, Any]) -> str:
    url = (folder.get("webViewLink") or "").strip()
    if url:
        return url
    folder_id = folder.get("id", "unknown")
    return f"https://drive.google.com/drive/folders/{folder_id}"


def _file_content_hash(file: dict[str, Any]) -> str:
    """Deterministic hash for a Drive file.

    For Google-native formats (no md5Checksum), modifiedTime + size serves as a
    sufficient proxy for content change detection.
    """
    payload = {
        "id": file.get("id", ""),
        "name": file.get("name", ""),
        "modified_time": file.get("modifiedTime", ""),
        "size": file.get("size"),
        "md5": file.get("md5Checksum"),
        "trashed": file.get("trashed", False),
    }
    return hash_dict(payload)


def _folder_content_hash(folder: dict[str, Any]) -> str:
    payload = {
        "id": folder.get("id", ""),
        "name": folder.get("name", ""),
        "modified_time": folder.get("modifiedTime", ""),
    }
    return hash_dict(payload)


def _first_parent(file: dict[str, Any]) -> str | None:
    parents = file.get("parents") or []
    return parents[0] if parents else None


def _owner_metadata(file: dict[str, Any]) -> tuple[str | None, str | None]:
    owners = file.get("owners") or []
    if not owners:
        return None, None
    first = owners[0]
    return first.get("displayName"), first.get("emailAddress")


def _permissions_snapshot(file: dict[str, Any]) -> dict[str, Any]:
    perms = file.get("permissions") or []
    return {
        "entries": [
            {
                "id": p.get("id"),
                "type": p.get("type"),
                "role": p.get("role"),
                "email": p.get("emailAddress"),
                "display_name": p.get("displayName"),
            }
            for p in perms
        ]
    }


def normalize_file(
    file: dict[str, Any],
    *,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Drive file resource into a NormalizedExternalItem."""
    file_id = file["id"]
    name = (file.get("name") or "").strip() or file_id
    mime_type = file.get("mimeType", "")
    owner_name, owner_email = _owner_metadata(file)

    native_export = NATIVE_EXPORT_MIME.get(mime_type) if is_google_native(mime_type) else None

    metadata = build_metadata(
        file_id=file_id,
        mime_type=mime_type,
        native_export_mime=native_export,
        size_bytes=file.get("size"),
        md5_checksum=file.get("md5Checksum"),
        created_time=file.get("createdTime"),
        modified_time=file.get("modifiedTime"),
        owner_display_name=owner_name,
        owner_email=owner_email,
        drive_id=file.get("driveId"),
        parent_id=_first_parent(file),
        is_google_native=True if is_google_native(mime_type) else None,
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=file_id,
        item_type=ExternalItemType.cloud_file,
        title=name,
        source_url=_file_url(file),
        content_hash=_file_content_hash(file),
        updated_at=_parse_datetime(file.get("modifiedTime") or file.get("createdTime")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=_first_parent(file),
        mime_type=mime_type or None,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
        permissions=_permissions_snapshot(file),
    )


def normalize_folder(
    folder: dict[str, Any],
    *,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Drive folder resource into a NormalizedExternalItem."""
    folder_id = folder["id"]
    name = (folder.get("name") or "").strip() or folder_id
    owner_name, owner_email = _owner_metadata(folder)

    metadata = build_metadata(
        folder_id=folder_id,
        created_time=folder.get("createdTime"),
        modified_time=folder.get("modifiedTime"),
        owner_display_name=owner_name,
        owner_email=owner_email,
        drive_id=folder.get("driveId"),
        parent_id=_first_parent(folder),
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=folder_id,
        item_type=ExternalItemType.folder,
        title=name,
        source_url=_folder_url(folder),
        content_hash=_folder_content_hash(folder),
        updated_at=_parse_datetime(folder.get("modifiedTime") or folder.get("createdTime")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=_first_parent(folder),
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
        permissions=_permissions_snapshot(folder),
    )
