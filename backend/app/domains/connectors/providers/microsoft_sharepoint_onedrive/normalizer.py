"""Microsoft Graph response normalization for SharePoint and OneDrive items."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.content_hash import hash_dict
from app.domains.connectors.sdk.metadata import build_metadata
from app.models.enums import ExternalItemType, ExternalItemVisibility

_PROVIDER_KEY = "microsoft-sharepoint-onedrive"


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _composite_item_id(drive_id: str, item_id: str) -> str:
    return f"item:{drive_id}:{item_id}"


def _composite_scope_id(kind: str, *parts: str) -> str:
    joined = ":".join(part.strip() for part in parts if part.strip())
    return f"{kind}:{joined}"


def _parent_id(drive_id: str, parent_reference: dict[str, Any] | None) -> str | None:
    if not parent_reference:
        return None
    parent_item_id = str(parent_reference.get("id") or "").strip()
    if not parent_item_id:
        return None
    return _composite_item_id(drive_id, parent_item_id)


def _root_id(site_id: str | None, drive_id: str) -> str:
    if site_id:
        return _composite_scope_id("site", site_id)
    return _composite_scope_id("drive", drive_id)


def _relative_folder_path(item: dict[str, Any]) -> str | None:
    parent_reference = item.get("parentReference") or {}
    path = str(parent_reference.get("path") or "").strip()
    if not path:
        return None
    if ":/" in path:
        _, relative = path.split(":/", 1)
        return relative.strip("/") or None
    return path.strip("/") or None


def _item_permissions(item: dict[str, Any], permissions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "entries": permissions,
        "source_permission_count": len(permissions),
        "item_id": item.get("id"),
    }


def normalize_drive_item(
    item: dict[str, Any],
    *,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    sync_version: int,
    site_id: str | None,
    drive_id: str,
    permissions: list[dict[str, Any]] | None = None,
) -> NormalizedExternalItem:
    """Normalize a Microsoft Graph driveItem into Rudix's connector item model."""
    item_id = str(item.get("id") or "").strip()
    if not item_id:
        raise ValueError("Microsoft Graph item is missing an id")

    name = str(item.get("name") or "").strip() or item_id
    web_url = str(item.get("webUrl") or "").strip()
    parent_reference = item.get("parentReference") or {}
    item_permissions = permissions or []
    is_folder = bool(item.get("folder"))
    is_deleted = "deleted" in item
    item_type = ExternalItemType.folder if is_folder else ExternalItemType.cloud_file
    provider_item_id = _composite_item_id(drive_id, item_id)
    provider_parent_id = _parent_id(drive_id, parent_reference)
    root_provider_item_id = _root_id(site_id, drive_id)
    size = item.get("size")
    last_modified = str(item.get("lastModifiedDateTime") or item.get("createdDateTime") or "")
    content_hash = hash_dict(
        {
            "drive_id": drive_id,
            "item_id": item_id,
            "name": name,
            "web_url": web_url,
            "parent_id": provider_parent_id,
            "site_id": site_id,
            "size": size,
            "etag": item.get("eTag"),
            "ctag": item.get("cTag"),
            "is_folder": is_folder,
            "is_deleted": is_deleted,
            "last_modified": last_modified,
        }
    )

    metadata = build_metadata(
        provider_item_id=provider_item_id,
        microsoft_item_id=item_id,
        site_id=site_id,
        drive_id=drive_id,
        folder_path=_relative_folder_path(item),
        web_url=web_url or None,
        size_bytes=size,
        mime_type=(item.get("file") or {}).get("mimeType"),
        e_tag=item.get("eTag"),
        c_tag=item.get("cTag"),
        created_time=item.get("createdDateTime"),
        modified_time=item.get("lastModifiedDateTime"),
        created_by=((item.get("createdBy") or {}).get("user") or {}).get("displayName"),
        modified_by=((item.get("lastModifiedBy") or {}).get("user") or {}).get("displayName"),
        owner=((item.get("owner") or {}).get("user") or {}).get("displayName"),
        deleted=is_deleted,
        is_folder=is_folder,
        source_url=web_url or None,
    )

    permissions_snapshot = _item_permissions(item, item_permissions)
    visibility = (
        ExternalItemVisibility.restricted
        if item_permissions
        else ExternalItemVisibility.org_wide
    )
    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=provider_item_id,
        item_type=item_type,
        title=name,
        source_url=web_url or f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}",
        content_hash=content_hash,
        updated_at=_parse_datetime(last_modified or None),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=provider_parent_id,
        root_provider_item_id=root_provider_item_id,
        mime_type=((item.get("file") or {}).get("mimeType") or None),
        visibility=visibility,
        acl_hash=hash_dict(item_permissions) if item_permissions else None,
        metadata=metadata,
        permissions=permissions_snapshot,
    )


def normalize_discovered_site(site: dict[str, Any]) -> dict[str, Any]:
    site_id = str(site.get("id") or "").strip()
    return {
        "provider_source_id": _composite_scope_id("site", site_id),
        "name": str(site.get("displayName") or site.get("name") or site_id).strip(),
        "source_type": "site",
        "source_url": str(site.get("webUrl") or "").strip() or None,
        "parent_provider_source_id": None,
        "metadata": {
            "site_id": site_id,
            "web_url": str(site.get("webUrl") or "").strip() or None,
            "hostname": ((site.get("siteCollection") or {}).get("hostname") or None),
            "description": site.get("description"),
        },
        "permissions": {},
    }


def normalize_discovered_drive(
    drive: dict[str, Any],
    *,
    site_id: str | None = None,
) -> dict[str, Any]:
    drive_id = str(drive.get("id") or "").strip()
    drive_type = str(drive.get("driveType") or "").strip() or "drive"
    source_type = "library" if drive_type == "documentLibrary" else "drive"
    return {
        "provider_source_id": _composite_scope_id("drive", drive_id),
        "name": str(drive.get("name") or drive_id).strip(),
        "source_type": source_type,
        "source_url": str(drive.get("webUrl") or "").strip() or None,
        "parent_provider_source_id": _composite_scope_id("site", site_id) if site_id else None,
        "metadata": {
            "drive_id": drive_id,
            "site_id": site_id,
            "drive_type": drive_type,
            "web_url": str(drive.get("webUrl") or "").strip() or None,
            "owner": ((drive.get("owner") or {}).get("user") or {}).get("displayName"),
        },
        "permissions": {},
    }


def normalize_discovered_folder(
    folder: dict[str, Any],
    *,
    drive_id: str,
    parent_provider_source_id: str | None = None,
) -> dict[str, Any]:
    folder_id = str(folder.get("id") or "").strip()
    item_id = _composite_item_id(drive_id, folder_id)
    return {
        "provider_source_id": _composite_scope_id("folder", drive_id, folder_id),
        "name": str(folder.get("name") or folder_id).strip(),
        "source_type": "folder",
        "source_url": str(folder.get("webUrl") or "").strip() or None,
        "parent_provider_source_id": parent_provider_source_id,
        "metadata": {
            "drive_id": drive_id,
            "folder_id": item_id,
            "web_url": str(folder.get("webUrl") or "").strip() or None,
            "path": _relative_folder_path(folder),
        },
        "permissions": {},
    }
