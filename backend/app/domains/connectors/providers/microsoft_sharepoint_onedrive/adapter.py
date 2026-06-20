"""Microsoft SharePoint / OneDrive connector adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.domains.connectors.providers.microsoft_sharepoint_onedrive.normalizer import (
    normalize_discovered_drive,
    normalize_discovered_folder,
    normalize_discovered_site,
    normalize_drive_item,
)
from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.rate_limits import raise_for_rate_limit
from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorContentError,
    ConnectorProviderAdapter,
    ConnectorProviderUnavailableError,
    ConnectorRateLimitError,
    DeltaItem,
    DeltaPage,
    ItemPage,
)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGE_SIZE = 200
_DEFAULT_MAX_FILE_SIZE_MB = 250
_DEFAULT_DOWNLOAD_RETRIES = 2

_PDF_EXPORT_FORMATS = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
}

_MIME_TO_EXTENSION = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
}


@dataclass(frozen=True)
class _Scope:
    kind: str
    site_id: str | None = None
    drive_id: str | None = None
    folder_id: str | None = None


def _bearer_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _raise_for_status(response: httpx.Response) -> None:
    raise_for_rate_limit(response.status_code, dict(response.headers))
    if response.status_code in (401, 403):
        raise ConnectorAuthError(
            f"Microsoft Graph returned {response.status_code}: credential is invalid or lacks required scope."
        )
    if response.status_code == 404:
        raise ConnectorContentError("Microsoft Graph could not find the requested item")
    if response.status_code >= 500:
        raise ConnectorProviderUnavailableError(
            f"Microsoft Graph returned {response.status_code}: provider unavailable."
        )
    response.raise_for_status()


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for raw in value:
        item = str(raw).strip()
        if item and item not in result:
            result.append(item)
    return result


def _split_composite_id(value: str) -> tuple[str, list[str]]:
    parts = [part.strip() for part in value.split(":") if part.strip()]
    if not parts:
        raise ValueError("provider identifier must not be blank")
    return parts[0], parts[1:]


def _parse_scope(provider_source_id: str | None, credential: dict[str, Any]) -> _Scope | None:
    if provider_source_id:
        kind, parts = _split_composite_id(provider_source_id)
        if kind == "site" and parts:
            return _Scope(kind="site", site_id=parts[0])
        if kind == "drive" and parts:
            return _Scope(kind="drive", drive_id=parts[0])
        if kind == "folder" and len(parts) >= 2:
            return _Scope(kind="folder", drive_id=parts[0], folder_id=parts[1])
        raise ValueError(f"unsupported provider_source_id: {provider_source_id}")

    site_ids = _normalize_string_list(credential.get("site_ids"))
    drive_ids = _normalize_string_list(credential.get("drive_ids"))
    folder_ids = _normalize_string_list(credential.get("folder_ids"))

    if folder_ids:
        # Folder IDs in config are expected to be Graph composite ids.
        kind, parts = _split_composite_id(folder_ids[0])
        if kind != "folder" or len(parts) < 2:
            raise ValueError("folder_ids must use the folder:<drive_id>:<folder_id> format")
        return _Scope(kind="folder", drive_id=parts[0], folder_id=parts[1])
    if drive_ids:
        kind, parts = _split_composite_id(drive_ids[0])
        if kind != "drive" or not parts:
            raise ValueError("drive_ids must use the drive:<drive_id> format")
        return _Scope(kind="drive", drive_id=parts[0])
    if site_ids:
        kind, parts = _split_composite_id(site_ids[0])
        if kind != "site" or not parts:
            raise ValueError("site_ids must use the site:<site_id> format")
        return _Scope(kind="site", site_id=parts[0])
    return None


def _allowed_file_types(credential: dict[str, Any]) -> set[str]:
    raw = credential.get("allowed_file_types") or credential.get("allowed_mime_types") or []
    if isinstance(raw, str):
        raw_values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        raw_values = [str(part).strip() for part in raw]
    else:
        raw_values = []
    return {value.lower() for value in raw_values if value}


def _mime_candidates(mime_type: str | None) -> set[str]:
    if not mime_type:
        return set()
    normalized = mime_type.lower().strip()
    candidates = {normalized}
    extension = _MIME_TO_EXTENSION.get(normalized)
    if extension:
        candidates.add(extension)
        candidates.add(extension.lstrip("."))
    return candidates


def _type_allowed(
    *,
    allowed_types: set[str],
    original_mime: str | None,
    export_mime: str,
    filename: str | None = None,
) -> bool:
    if not allowed_types:
        return True

    candidates = set(_mime_candidates(original_mime))
    candidates.update(_mime_candidates(export_mime))
    if filename:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix:
            candidates.add(suffix)
            candidates.add(f".{suffix}")
    return any(candidate in allowed_types for candidate in candidates)


def _max_file_size_bytes(credential: dict[str, Any]) -> int:
    raw_mb = credential.get("max_file_size_mb")
    try:
        if raw_mb is None:
            return _DEFAULT_MAX_FILE_SIZE_MB * 1024 * 1024
        size_mb = int(raw_mb)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_FILE_SIZE_MB * 1024 * 1024
    return max(1, size_mb) * 1024 * 1024


def _permission_import_behavior(credential: dict[str, Any]) -> str:
    behavior = str(credential.get("permission_import_behavior") or "direct").strip().lower()
    return behavior if behavior in {"none", "direct"} else "direct"


def _file_mime_type(item: dict[str, Any]) -> str | None:
    file_facet = item.get("file") or {}
    mime_type = file_facet.get("mimeType") or item.get("mimeType")
    if mime_type:
        return str(mime_type).strip().lower()
    return None


def _is_folder(item: dict[str, Any]) -> bool:
    return bool(item.get("folder"))


def _is_deleted(item: dict[str, Any]) -> bool:
    return "deleted" in item


class MicrosoftSharePointOneDriveConnectorAdapter(ConnectorProviderAdapter):
    """Microsoft Graph adapter that supports SharePoint sites and OneDrive drives."""

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_DOWNLOAD_RETRIES,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max(0, max_retries)

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
        access_token = str(decrypted_credential.get("access_token") or "").strip()
        if not access_token:
            raise ConnectorAuthError("Microsoft credential is missing an access token")

        scope = _parse_scope(provider_source_id, decrypted_credential)
        if scope is None:
            return ItemPage(items=[], next_cursor=None, has_more=False)

        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None
        page = await self._page_for_scope(
            scope,
            access_token=access_token,
            cursor=cursor,
            page_size=max(1, min(page_size, _MAX_PAGE_SIZE)),
            organization_id=org_uuid,
            connection_id=conn_uuid,
            external_source_id=ext_src_uuid,
            decrypted_credential=decrypted_credential,
            include_deletions=False,
        )
        return page

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
        access_token = str(decrypted_credential.get("access_token") or "").strip()
        if not access_token:
            raise ConnectorAuthError("Microsoft credential is missing an access token")

        scope = _parse_scope(provider_source_id, decrypted_credential)
        if scope is None:
            return DeltaPage(items=[], next_cursor=None, has_more=False)

        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None
        page = await self._delta_page_for_scope(
            scope,
            access_token=access_token,
            cursor=cursor,
            page_size=max(1, min(page_size, _MAX_PAGE_SIZE)),
            organization_id=org_uuid,
            connection_id=conn_uuid,
            external_source_id=ext_src_uuid,
            decrypted_credential=decrypted_credential,
        )
        return page

    async def download_file_content(
        self,
        *,
        provider_item_id: str,
        mime_type: str | None,
        decrypted_credential: dict,
    ) -> tuple[bytes, str, str] | None:
        access_token = str(decrypted_credential.get("access_token") or "").strip()
        if not access_token:
            raise ConnectorAuthError("Microsoft credential is missing an access token")

        allowed_types = _allowed_file_types(decrypted_credential)
        kind, parts = _split_composite_id(provider_item_id)
        if kind != "item" or len(parts) < 2:
            return None

        drive_id, item_id = parts[0], parts[1]
        item = await self._get_item(
            access_token=access_token,
            drive_id=drive_id,
            item_id=item_id,
        )
        if _is_folder(item) or _is_deleted(item):
            return None

        resolved_mime = _file_mime_type(item) or mime_type or "application/octet-stream"

        max_size = _max_file_size_bytes(decrypted_credential)
        size = int(item.get("size") or 0)
        if size and size > max_size:
            return None

        export_mime = (
            "application/pdf" if resolved_mime not in {"application/pdf"} else resolved_mime
        )
        if not _type_allowed(
            allowed_types=allowed_types,
            original_mime=resolved_mime,
            export_mime=export_mime,
            filename=str(item.get("name") or "").strip() or None,
        ):
            return None
        endpoint = f"{_GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"
        params: dict[str, Any] = {}
        if export_mime != "application/pdf":
            params["format"] = "pdf"
            export_mime = "application/pdf"

        content = await self._download_bytes(
            access_token=access_token,
            url=endpoint,
            params=params or None,
        )
        if not content:
            return None

        extension = ".pdf" if export_mime == "application/pdf" else ".bin"
        filename = f"{str(item.get('name') or item_id).strip()}{extension}"
        return content, filename, export_mime

    async def discover_sites(
        self,
        *,
        access_token: str,
        page_size: int = 50,
        cursor: dict | None = None,
    ) -> tuple[list[dict[str, Any]], dict | None, bool]:
        params: dict[str, Any] = {
            "search": "*",
            "$top": max(1, min(page_size, _MAX_PAGE_SIZE)),
        }
        if cursor and cursor.get("next_url"):
            data = await self._request_json(
                access_token=access_token,
                url=str(cursor["next_url"]),
            )
        else:
            data = await self._request_json(
                access_token=access_token,
                url=f"{_GRAPH_BASE}/sites",
                params=params,
            )
        values = data.get("value") or []
        sites = [normalize_discovered_site(site) for site in values if isinstance(site, dict)]
        next_url = data.get("@odata.nextLink")
        return sites, ({"next_url": next_url} if next_url else None), bool(next_url)

    async def discover_site_drives(
        self,
        *,
        access_token: str,
        site_id: str,
    ) -> list[dict[str, Any]]:
        data = await self._request_json(
            access_token=access_token,
            url=f"{_GRAPH_BASE}/sites/{site_id}/drives",
        )
        values = data.get("value") or []
        return [
            normalize_discovered_drive(drive, site_id=site_id)
            for drive in values
            if isinstance(drive, dict)
        ]

    async def discover_my_drives(self, *, access_token: str) -> list[dict[str, Any]]:
        data = await self._request_json(
            access_token=access_token,
            url=f"{_GRAPH_BASE}/me/drives",
        )
        values = data.get("value") or []
        return [
            normalize_discovered_drive(drive, site_id=None)
            for drive in values
            if isinstance(drive, dict)
        ]

    async def discover_drive_children(
        self,
        *,
        access_token: str,
        drive_id: str,
        folder_id: str | None = None,
    ) -> list[dict[str, Any]]:
        url = (
            f"{_GRAPH_BASE}/drives/{drive_id}/items/{folder_id}/children"
            if folder_id
            else f"{_GRAPH_BASE}/drives/{drive_id}/root/children"
        )
        data = await self._request_json(access_token=access_token, url=url)
        values = data.get("value") or []
        parent_source_id = f"folder:{drive_id}:{folder_id}" if folder_id else f"drive:{drive_id}"
        return [
            normalize_discovered_folder(
                item,
                drive_id=drive_id,
                parent_provider_source_id=parent_source_id,
            )
            for item in values
            if isinstance(item, dict) and _is_folder(item)
        ]

    async def _page_for_scope(
        self,
        scope: _Scope,
        *,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
        include_deletions: bool,
    ) -> ItemPage:
        if scope.kind == "site":
            return await self._page_for_site(
                scope.site_id or "",
                access_token=access_token,
                cursor=cursor,
                page_size=page_size,
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                decrypted_credential=decrypted_credential,
                include_deletions=include_deletions,
            )
        if scope.kind == "drive":
            return await self._page_for_drive(
                drive_id=scope.drive_id or "",
                access_token=access_token,
                cursor=cursor,
                page_size=page_size,
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                decrypted_credential=decrypted_credential,
                include_deletions=include_deletions,
            )
        if scope.kind == "folder":
            return await self._page_for_folder(
                drive_id=scope.drive_id or "",
                folder_id=scope.folder_id or "",
                access_token=access_token,
                cursor=cursor,
                page_size=page_size,
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                decrypted_credential=decrypted_credential,
                include_deletions=include_deletions,
            )
        raise ValueError(f"unsupported scope kind: {scope.kind}")

    async def _delta_page_for_scope(
        self,
        scope: _Scope,
        *,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
    ) -> DeltaPage:
        if scope.kind == "site":
            return await self._delta_page_for_site(
                scope.site_id or "",
                access_token=access_token,
                cursor=cursor,
                page_size=page_size,
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                decrypted_credential=decrypted_credential,
            )
        if scope.kind == "drive":
            return await self._delta_page_for_drive(
                drive_id=scope.drive_id or "",
                access_token=access_token,
                cursor=cursor,
                page_size=page_size,
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                decrypted_credential=decrypted_credential,
            )
        if scope.kind == "folder":
            return await self._delta_page_for_folder(
                drive_id=scope.drive_id or "",
                folder_id=scope.folder_id or "",
                access_token=access_token,
                cursor=cursor,
                page_size=page_size,
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                decrypted_credential=decrypted_credential,
            )
        raise ValueError(f"unsupported scope kind: {scope.kind}")

    async def _page_for_site(
        self,
        site_id: str,
        *,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
        include_deletions: bool,
    ) -> ItemPage:
        state = dict(cursor or {})
        drive_queue = state.get("drive_queue")
        if not isinstance(drive_queue, list):
            drives = await self.discover_site_drives(access_token=access_token, site_id=site_id)
            drive_queue = [drive["provider_source_id"] for drive in drives]
        drive_index = int(state.get("drive_index", 0))
        drive_cursor = state.get("drive_cursor") or {}

        collected: list[NormalizedExternalItem] = []
        while drive_index < len(drive_queue) and len(collected) < page_size:
            drive_scope = _Scope(
                kind="drive", drive_id=_split_composite_id(drive_queue[drive_index])[1][0]
            )
            drive_page = await self._page_for_drive(
                drive_id=drive_scope.drive_id or "",
                access_token=access_token,
                cursor=drive_cursor,
                page_size=page_size - len(collected),
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                decrypted_credential=decrypted_credential,
                include_deletions=include_deletions,
                site_id=site_id,
            )
            collected.extend(drive_page.items)
            if drive_page.has_more:
                return ItemPage(
                    items=collected,
                    next_cursor={
                        "drive_queue": drive_queue,
                        "drive_index": drive_index,
                        "drive_cursor": drive_page.next_cursor or {},
                        "site_id": site_id,
                    },
                    has_more=True,
                )
            drive_index += 1
            drive_cursor = {}

        has_more = drive_index < len(drive_queue)
        next_cursor = (
            {
                "drive_queue": drive_queue,
                "drive_index": drive_index,
                "drive_cursor": {},
                "site_id": site_id,
            }
            if has_more
            else None
        )
        return ItemPage(items=collected, next_cursor=next_cursor, has_more=has_more)

    async def _delta_page_for_site(
        self,
        site_id: str,
        *,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
    ) -> DeltaPage:
        state = dict(cursor or {})
        drive_queue = state.get("drive_queue")
        if not isinstance(drive_queue, list):
            drives = await self.discover_site_drives(access_token=access_token, site_id=site_id)
            drive_queue = [drive["provider_source_id"] for drive in drives]
        drive_index = int(state.get("drive_index", 0))
        drive_cursor = state.get("drive_cursor") or {}

        collected: list[DeltaItem] = []
        while drive_index < len(drive_queue) and len(collected) < page_size:
            drive_kind, drive_parts = _split_composite_id(str(drive_queue[drive_index]))
            if drive_kind != "drive" or not drive_parts:
                raise ValueError("site drive queue must contain drive:<drive_id> entries")
            drive_page = await self._delta_page_for_drive(
                drive_id=drive_parts[0],
                access_token=access_token,
                cursor=drive_cursor,
                page_size=page_size - len(collected),
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                decrypted_credential=decrypted_credential,
                site_id=site_id,
            )
            collected.extend(drive_page.items)
            if drive_page.has_more:
                return DeltaPage(
                    items=collected,
                    next_cursor={
                        "drive_queue": drive_queue,
                        "drive_index": drive_index,
                        "drive_cursor": drive_page.next_cursor or {},
                        "site_id": site_id,
                    },
                    has_more=True,
                )
            drive_index += 1
            drive_cursor = {}

        has_more = drive_index < len(drive_queue)
        next_cursor = (
            {
                "drive_queue": drive_queue,
                "drive_index": drive_index,
                "drive_cursor": {},
                "site_id": site_id,
            }
            if has_more
            else None
        )
        return DeltaPage(items=collected, next_cursor=next_cursor, has_more=has_more)

    async def _page_for_drive(
        self,
        *,
        drive_id: str,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
        include_deletions: bool,
        site_id: str | None = None,
    ) -> ItemPage:
        return await self._page_for_drive_or_folder(
            access_token=access_token,
            drive_id=drive_id,
            folder_id=None,
            cursor=cursor,
            page_size=page_size,
            organization_id=organization_id,
            connection_id=connection_id,
            external_source_id=external_source_id,
            decrypted_credential=decrypted_credential,
            include_deletions=include_deletions,
            site_id=site_id,
        )

    async def _delta_page_for_drive(
        self,
        *,
        drive_id: str,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
        site_id: str | None = None,
    ) -> DeltaPage:
        return await self._delta_page_for_drive_or_folder(
            access_token=access_token,
            drive_id=drive_id,
            folder_id=None,
            cursor=cursor,
            page_size=page_size,
            organization_id=organization_id,
            connection_id=connection_id,
            external_source_id=external_source_id,
            decrypted_credential=decrypted_credential,
            site_id=site_id,
        )

    async def _page_for_folder(
        self,
        *,
        drive_id: str,
        folder_id: str,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
        include_deletions: bool,
        site_id: str | None = None,
    ) -> ItemPage:
        return await self._page_for_drive_or_folder(
            access_token=access_token,
            drive_id=drive_id,
            folder_id=folder_id,
            cursor=cursor,
            page_size=page_size,
            organization_id=organization_id,
            connection_id=connection_id,
            external_source_id=external_source_id,
            decrypted_credential=decrypted_credential,
            include_deletions=include_deletions,
            site_id=site_id,
        )

    async def _delta_page_for_folder(
        self,
        *,
        drive_id: str,
        folder_id: str,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
        site_id: str | None = None,
    ) -> DeltaPage:
        return await self._delta_page_for_drive_or_folder(
            access_token=access_token,
            drive_id=drive_id,
            folder_id=folder_id,
            cursor=cursor,
            page_size=page_size,
            organization_id=organization_id,
            connection_id=connection_id,
            external_source_id=external_source_id,
            decrypted_credential=decrypted_credential,
            site_id=site_id,
        )

    async def _page_for_drive_or_folder(
        self,
        *,
        access_token: str,
        drive_id: str,
        folder_id: str | None,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
        include_deletions: bool,
        site_id: str | None = None,
    ) -> ItemPage:
        url = str(cursor.get("next_url") or "").strip()
        if not url:
            if folder_id:
                url = f"{_GRAPH_BASE}/drives/{drive_id}/items/{folder_id}/delta"
            else:
                url = f"{_GRAPH_BASE}/drives/{drive_id}/root/delta"
        data = await self._request_json(
            access_token=access_token,
            url=url,
            params={"$top": page_size} if "delta" in url and "?" not in url else None,
        )
        values = data.get("value") or []
        items: list[NormalizedExternalItem] = []
        for raw_item in values:
            if not isinstance(raw_item, dict):
                continue
            if _is_deleted(raw_item):
                if include_deletions:
                    # Deletions are surfaced by delta_sync only.  Full sync ignores them.
                    continue
                continue
            permissions = []
            if _permission_import_behavior(decrypted_credential) != "none":
                permissions = await self._get_permissions(
                    access_token=access_token,
                    drive_id=drive_id,
                    item_id=str(raw_item.get("id") or "").strip(),
                )
            items.append(
                normalize_drive_item(
                    raw_item,
                    organization_id=organization_id,
                    connection_id=connection_id,
                    external_source_id=external_source_id,
                    sync_version=1,
                    site_id=site_id,
                    drive_id=drive_id,
                    permissions=permissions,
                )
            )

        next_url = data.get("@odata.nextLink")
        next_cursor = {"next_url": next_url} if next_url else None
        return ItemPage(items=items, next_cursor=next_cursor, has_more=bool(next_url))

    async def _delta_page_for_drive_or_folder(
        self,
        *,
        access_token: str,
        drive_id: str,
        folder_id: str | None,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        decrypted_credential: dict,
        site_id: str | None = None,
    ) -> DeltaPage:
        url = str(cursor.get("next_url") or "").strip()
        if not url:
            if folder_id:
                url = f"{_GRAPH_BASE}/drives/{drive_id}/items/{folder_id}/delta"
            else:
                url = f"{_GRAPH_BASE}/drives/{drive_id}/root/delta"
        data = await self._request_json(
            access_token=access_token,
            url=url,
            params={"$top": page_size} if "delta" in url and "?" not in url else None,
        )

        delta_items: list[DeltaItem] = []
        for raw_item in data.get("value") or []:
            if not isinstance(raw_item, dict):
                continue
            item_id = str(raw_item.get("id") or "").strip()
            if not item_id:
                continue
            provider_item_id = f"item:{drive_id}:{item_id}"
            if _is_deleted(raw_item):
                delta_items.append(DeltaItem(provider_item_id=provider_item_id, is_deleted=True))
                continue
            permissions = []
            if _permission_import_behavior(decrypted_credential) != "none":
                permissions = await self._get_permissions(
                    access_token=access_token,
                    drive_id=drive_id,
                    item_id=item_id,
                )
            normalized = normalize_drive_item(
                raw_item,
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                sync_version=1,
                site_id=site_id,
                drive_id=drive_id,
                permissions=permissions,
            )
            delta_items.append(
                DeltaItem(provider_item_id=provider_item_id, is_deleted=False, item=normalized)
            )

        next_url = data.get("@odata.nextLink")
        next_cursor = {"next_url": next_url} if next_url else None
        return DeltaPage(items=delta_items, next_cursor=next_cursor, has_more=bool(next_url))

    async def _get_item(
        self,
        *,
        access_token: str,
        drive_id: str,
        item_id: str,
    ) -> dict[str, Any]:
        return await self._request_json(
            access_token=access_token,
            url=f"{_GRAPH_BASE}/drives/{drive_id}/items/{item_id}",
            params={
                "$select": (
                    "id,name,size,webUrl,createdDateTime,lastModifiedDateTime,"
                    "parentReference,file,folder,deleted,eTag,cTag,createdBy,lastModifiedBy,"
                    "sharepointIds"
                )
            },
        )

    async def _get_permissions(
        self,
        *,
        access_token: str,
        drive_id: str,
        item_id: str,
    ) -> list[dict[str, Any]]:
        data = await self._request_json(
            access_token=access_token,
            url=f"{_GRAPH_BASE}/drives/{drive_id}/items/{item_id}/permissions",
        )
        permissions = []
        for entry in data.get("value") or []:
            if not isinstance(entry, dict):
                continue
            permissions.append(
                {
                    "id": entry.get("id"),
                    "roles": entry.get("roles") or [],
                    "grantedToV2": entry.get("grantedToV2"),
                    "grantedToIdentitiesV2": entry.get("grantedToIdentitiesV2"),
                    "inheritedFrom": entry.get("inheritedFrom"),
                    "link": entry.get("link"),
                }
            )
        return permissions

    async def _download_bytes(
        self,
        *,
        access_token: str,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        response = await self._request_response(
            access_token=access_token,
            url=url,
            params=params,
            follow_redirects=True,
        )
        return response.content

    async def _request_json(
        self,
        *,
        access_token: str,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._request_response(
            access_token=access_token,
            url=url,
            params=params,
        )
        data = response.json()
        if not isinstance(data, dict):
            raise ConnectorProviderUnavailableError("Microsoft Graph returned an invalid payload")
        return data

    async def _request_response(
        self,
        *,
        access_token: str,
        url: str,
        params: dict[str, Any] | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(
                        url,
                        params=params,
                        headers=_bearer_headers(access_token),
                        follow_redirects=follow_redirects,
                    )
                _raise_for_status(response)
                return response
            except ConnectorRateLimitError:
                raise
            except ConnectorAuthError:
                raise
            except ConnectorContentError:
                raise
            except (httpx.TimeoutException, ConnectorProviderUnavailableError) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                await asyncio.sleep(min(2**attempt, 4))
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
                await asyncio.sleep(min(2**attempt, 4))
        if isinstance(last_error, ConnectorProviderUnavailableError):
            raise last_error
        if isinstance(last_error, ConnectorContentError):
            raise last_error
        if isinstance(last_error, ConnectorAuthError):
            raise last_error
        if isinstance(last_error, ConnectorRateLimitError):
            raise last_error
        raise ConnectorProviderUnavailableError("Microsoft Graph request failed")


__all__ = ["MicrosoftSharePointOneDriveConnectorAdapter"]
