"""Google Drive connector adapter.

Implements the ConnectorProviderAdapter contract using the Google Drive API v3.

Credential dict shape (OAuth2, stored in decrypted_credential):
    {
        "auth_type": "oauth2",
        "access_token": "<token>",
        "refresh_token": "<token>",         # optional
        "folder_ids": ["folder_id_1"],      # optional – root folders to sync recursively
        "drive_ids": ["drive_id_1"],        # optional – shared drive IDs to include
        "include_shared_drives": true,      # optional – default False
    }

provider_source_id: a folder ID for scoped recursive sync, or None for full drive scan.

Cursor shapes:
  Full scan:         {"page_token": null_or_str}
  Folder traversal:  {"folder_queue": [...], "current_folder": str|null, "page_token": null_or_str}
  Delta sync:        {"since": "ISO-8601", "page_token": null_or_str}
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from app.domains.connectors.providers.google_drive.normalizer import (
    NATIVE_EXPORT_MIME,
    UNSUPPORTED_MIME_TYPES,
    is_google_folder,
    is_google_native,
    normalize_file,
    normalize_folder,
)
from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.rate_limits import raise_for_rate_limit
from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorProviderAdapter,
    ConnectorProviderUnavailableError,
    DeltaItem,
    DeltaPage,
    ItemPage,
)

_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_MIME_TO_EXTENSION: dict[str, str] = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def _mime_to_extension(mime_type: str) -> str:
    return _MIME_TO_EXTENSION.get(mime_type, ".bin")


_FILE_FIELDS = (
    "nextPageToken,"
    "files("
    "id,name,mimeType,parents,modifiedTime,createdTime,"
    "webViewLink,owners,permissions,size,md5Checksum,trashed,driveId"
    ")"
)
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGE_SIZE = 1000


def _bearer_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _raise_for_status(response: httpx.Response) -> None:
    raise_for_rate_limit(response.status_code, dict(response.headers))
    if response.status_code in (401, 403):
        raise ConnectorAuthError(
            f"Google Drive returned {response.status_code}: "
            "credential is invalid or has insufficient scope."
        )
    if response.status_code >= 500:
        raise ConnectorProviderUnavailableError(
            f"Google Drive returned {response.status_code}: provider unavailable."
        )
    response.raise_for_status()


def _get_root_folders(
    provider_source_id: str | None,
    credential: dict[str, Any],
) -> list[str] | None:
    """Return root folder IDs for folder-scoped sync, or None for full drive scan."""
    if provider_source_id:
        return [provider_source_id]
    folder_ids = credential.get("folder_ids")
    if isinstance(folder_ids, list) and folder_ids:
        return [str(f).strip() for f in folder_ids if str(f).strip()]
    return None


def _normalize_files(
    files: list[dict[str, Any]],
    *,
    org_uuid: UUID,
    conn_uuid: UUID,
    ext_src_uuid: UUID | None,
) -> list[NormalizedExternalItem]:
    items: list[NormalizedExternalItem] = []
    for file in files:
        if is_google_folder(file.get("mimeType")):
            items.append(
                normalize_folder(
                    file,
                    organization_id=org_uuid,
                    connection_id=conn_uuid,
                    external_source_id=ext_src_uuid,
                    sync_version=1,
                )
            )
        else:
            items.append(
                normalize_file(
                    file,
                    organization_id=org_uuid,
                    connection_id=conn_uuid,
                    external_source_id=ext_src_uuid,
                    sync_version=1,
                )
            )
    return items


class GoogleDriveConnectorAdapter(ConnectorProviderAdapter):
    """Google Drive adapter: full sync + delta sync, recursive folder traversal, shared drives."""

    def __init__(self, *, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    # ------------------------------------------------------------------
    # ConnectorProviderAdapter contract
    # ------------------------------------------------------------------

    async def list_items(
        self,
        *,
        organization_id: str,
        connection_id: str,
        external_source_id: str | None,
        provider_source_id: str | None,
        decrypted_credential: dict,
        cursor: dict,
        page_size: int,
    ) -> ItemPage:
        """Full sync: list all non-trashed files/folders, optionally scoped to a folder tree."""
        access_token = decrypted_credential.get("access_token", "")
        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None

        root_folders = _get_root_folders(provider_source_id, decrypted_credential)

        # Resume an in-progress folder traversal even when no provider_source_id is present
        # (e.g. when the sync engine resumes from a checkpointed cursor).
        in_progress_traversal = "folder_queue" in cursor or "current_folder" in cursor

        if root_folders or in_progress_traversal:
            return await self._list_items_folder_scoped(
                access_token=access_token,
                root_folders=root_folders or [],
                cursor=cursor,
                page_size=page_size,
                org_uuid=org_uuid,
                conn_uuid=conn_uuid,
                ext_src_uuid=ext_src_uuid,
            )

        include_shared = bool(decrypted_credential.get("include_shared_drives", False))
        page_token = cursor.get("page_token") or None

        files, next_page_token = await self._list_files(
            access_token=access_token,
            query="trashed = false",
            page_token=page_token,
            page_size=page_size,
            include_shared_drives=include_shared,
        )

        items = _normalize_files(
            files,
            org_uuid=org_uuid,
            conn_uuid=conn_uuid,
            ext_src_uuid=ext_src_uuid,
        )
        next_cursor = {"page_token": next_page_token} if next_page_token else None
        return ItemPage(items=items, next_cursor=next_cursor, has_more=bool(next_page_token))

    async def delta_sync(
        self,
        *,
        organization_id: str,
        connection_id: str,
        external_source_id: str | None,
        provider_source_id: str | None,
        decrypted_credential: dict,
        cursor: dict,
        page_size: int,
    ) -> DeltaPage:
        """Incremental sync: return files modified since cursor['since'].

        Files with trashed=True are surfaced as deletions.
        """
        access_token = decrypted_credential.get("access_token", "")
        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None
        include_shared = bool(decrypted_credential.get("include_shared_drives", False))

        since = cursor.get("since")
        page_token = cursor.get("page_token") or None

        if since:
            # Query both trashed and live files changed since the cursor timestamp.
            # Trashed files are treated as deletions.
            query = f"modifiedTime > '{since}'"
        else:
            query = "trashed = false"

        files, next_page_token = await self._list_files(
            access_token=access_token,
            query=query,
            page_token=page_token,
            page_size=page_size,
            include_shared_drives=include_shared,
        )

        delta_items: list[DeltaItem] = []
        latest_modified = since

        for file in files:
            file_id = file["id"]
            is_deleted = bool(file.get("trashed", False))

            if is_deleted:
                delta_items.append(DeltaItem(provider_item_id=file_id, is_deleted=True, item=None))
            else:
                item = (
                    normalize_folder(
                        file,
                        organization_id=org_uuid,
                        connection_id=conn_uuid,
                        external_source_id=ext_src_uuid,
                        sync_version=1,
                    )
                    if is_google_folder(file.get("mimeType"))
                    else normalize_file(
                        file,
                        organization_id=org_uuid,
                        connection_id=conn_uuid,
                        external_source_id=ext_src_uuid,
                        sync_version=1,
                    )
                )
                delta_items.append(DeltaItem(provider_item_id=file_id, is_deleted=False, item=item))

            modified_time = file.get("modifiedTime", "")
            if modified_time and (latest_modified is None or modified_time > latest_modified):
                latest_modified = modified_time

        new_since = latest_modified or datetime.now(UTC).isoformat()
        has_more = bool(next_page_token)
        next_cursor: dict[str, Any] = {
            "since": new_since,
            "page_token": next_page_token if has_more else None,
        }
        return DeltaPage(items=delta_items, next_cursor=next_cursor, has_more=has_more)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _list_items_folder_scoped(
        self,
        *,
        access_token: str,
        root_folders: list[str],
        cursor: dict,
        page_size: int,
        org_uuid: UUID,
        conn_uuid: UUID,
        ext_src_uuid: UUID | None,
    ) -> ItemPage:
        """Queue-based recursive folder traversal.

        The cursor carries the traversal state across calls so the sync engine can
        checkpoint and resume mid-tree.  Each call processes one page of one folder
        and enqueues discovered sub-folders for subsequent calls.
        """
        if "folder_queue" not in cursor and "current_folder" not in cursor:
            folder_queue: list[str] = list(root_folders)
            current_folder: str | None = folder_queue.pop(0) if folder_queue else None
            page_token: str | None = None
        else:
            folder_queue = list(cursor.get("folder_queue", []))
            current_folder = cursor.get("current_folder")
            page_token = cursor.get("page_token") or None

            if current_folder is None and folder_queue:
                current_folder = folder_queue.pop(0)
                page_token = None

        if not current_folder:
            return ItemPage(items=[], next_cursor=None, has_more=False)

        query = f"'{current_folder}' in parents and trashed = false"
        files, next_page_token = await self._list_files(
            access_token=access_token,
            query=query,
            page_token=page_token,
            page_size=page_size,
        )

        items: list[NormalizedExternalItem] = []
        discovered_subfolders: list[str] = []

        for file in files:
            if is_google_folder(file.get("mimeType")):
                items.append(
                    normalize_folder(
                        file,
                        organization_id=org_uuid,
                        connection_id=conn_uuid,
                        external_source_id=ext_src_uuid,
                        sync_version=1,
                    )
                )
                discovered_subfolders.append(file["id"])
            else:
                items.append(
                    normalize_file(
                        file,
                        organization_id=org_uuid,
                        connection_id=conn_uuid,
                        external_source_id=ext_src_uuid,
                        sync_version=1,
                    )
                )

        new_folder_queue = folder_queue + discovered_subfolders

        next_cursor: dict[str, Any] | None
        if next_page_token:
            next_cursor = {
                "current_folder": current_folder,
                "folder_queue": new_folder_queue,
                "page_token": next_page_token,
            }
        elif new_folder_queue:
            next_cursor = {
                "current_folder": None,
                "folder_queue": new_folder_queue,
                "page_token": None,
            }
        else:
            next_cursor = None

        return ItemPage(
            items=items,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
        )

    async def download_file_content(
        self,
        *,
        provider_item_id: str,
        mime_type: str | None,
        decrypted_credential: dict,
    ) -> tuple[bytes, str, str] | None:
        """Download raw bytes for a Drive file.

        Google-native formats are exported to a supported target MIME type.
        Folders and unsupported shortcut types return None.
        Returns (content_bytes, filename, resolved_mime_type).
        """
        if not mime_type or mime_type in UNSUPPORTED_MIME_TYPES or is_google_folder(mime_type):
            return None

        access_token = decrypted_credential.get("access_token", "")
        headers = _bearer_headers(access_token)

        if is_google_native(mime_type):
            export_mime = NATIVE_EXPORT_MIME.get(mime_type, "text/plain")
            url = f"{_DRIVE_FILES_URL}/{provider_item_id}/export"
            params: dict[str, Any] = {"mimeType": export_mime}
        else:
            export_mime = mime_type
            url = f"{_DRIVE_FILES_URL}/{provider_item_id}"
            params = {"alt": "media"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, params=params, headers=headers)
        _raise_for_status(response)

        content = response.content
        if not content:
            return None

        ext = _mime_to_extension(export_mime)
        filename = f"{provider_item_id}{ext}"
        return content, filename, export_mime

    async def _list_files(
        self,
        *,
        access_token: str,
        query: str,
        page_token: str | None,
        page_size: int,
        include_shared_drives: bool = False,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return (files, nextPageToken) from the Drive files.list endpoint."""
        params: dict[str, Any] = {
            "q": query,
            "fields": _FILE_FIELDS,
            "pageSize": min(page_size, _MAX_PAGE_SIZE),
            "orderBy": "modifiedTime asc",
        }
        if page_token:
            params["pageToken"] = page_token
        if include_shared_drives:
            params["includeItemsFromAllDrives"] = "true"
            params["supportsAllDrives"] = "true"
            params["corpora"] = "allDrives"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                _DRIVE_FILES_URL,
                params=params,
                headers=_bearer_headers(access_token),
            )
        _raise_for_status(response)
        data = response.json()
        return data.get("files", []), data.get("nextPageToken")
