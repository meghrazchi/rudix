"""Notion connector adapter.

Implements the ConnectorProviderAdapter contract using the Notion REST API v1.

Credential dict shape (OAuth2, stored in decrypted_credential):
    {
        "auth_type": "oauth2",
        "access_token": "<integration-token>",
        "workspace_id": "workspace-uuid",         # from OAuth callback; used as root_id
        "page_ids": ["page-id"],                   # optional – scope to specific pages
        "database_ids": ["db-id"],                 # optional – scope to specific databases
        "include_child_pages": true,               # optional, default True
        "include_comments": false,                 # optional, default False
        "include_attachments": false,              # optional, default False
        "max_page_depth": 5,                       # optional, default 5 (block traversal)
        "import_property_metadata": true,          # optional, default True
    }

Full-sync cursor:  {"start_cursor": null | str}
Delta-sync cursor: {"start_cursor": null | str, "since": "ISO-8601"}
Scoped cursor:     {"page_index": int, "db_index": int}
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from app.domains.connectors.providers.notion.normalizer import (
    NOTION_FILE_BLOCK_TYPES,
    extract_page_title,
    normalize_comment,
    normalize_database,
    normalize_file_block,
    normalize_page,
    render_blocks_to_text,
)
from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.rate_limits import parse_retry_after, raise_for_rate_limit
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

_NOTION_API_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_DEFAULT_TIMEOUT = 30.0
_MAX_PAGE_SIZE = 100
_DEFAULT_MAX_DEPTH = 5
_DEFAULT_DOWNLOAD_RETRIES = 2
_MAX_BLOCK_FETCH_DEPTH = 10


def _auth_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _raise_for_status(response: httpx.Response) -> None:
    raise_for_rate_limit(response.status_code, dict(response.headers))
    if response.status_code in (401, 403):
        raise ConnectorAuthError(
            f"Notion API returned {response.status_code}: credential is invalid or lacks required access."
        )
    if response.status_code == 404:
        raise ConnectorContentError("Notion API could not find the requested resource")
    if response.status_code >= 500:
        raise ConnectorProviderUnavailableError(
            f"Notion API returned {response.status_code}: provider unavailable."
        )
    response.raise_for_status()


def _require_access_token(credential: dict[str, Any]) -> str:
    token = str(credential.get("access_token") or "").strip()
    if not token:
        raise ConnectorAuthError("Notion credential is missing an access_token.")
    return token


def _workspace_id(credential: dict[str, Any]) -> str | None:
    return str(credential.get("workspace_id") or "").strip() or None


def _scoped_page_ids(
    credential: dict[str, Any],
    provider_source_id: str | None,
) -> list[str] | None:
    if provider_source_id:
        return [provider_source_id]
    ids = credential.get("page_ids")
    if isinstance(ids, list) and ids:
        return [str(i).strip() for i in ids if str(i).strip()]
    return None


def _scoped_database_ids(credential: dict[str, Any]) -> list[str] | None:
    ids = credential.get("database_ids")
    if isinstance(ids, list) and ids:
        return [str(i).strip() for i in ids if str(i).strip()]
    return None


class NotionConnectorAdapter(ConnectorProviderAdapter):
    """Notion adapter: full sync + delta sync via search API.

    Pages (including database items) are returned as cloud_file/text/plain items
    so the sync engine fetches their block content and routes it through the
    document ingestion pipeline.  Databases are returned as folder items.
    """

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_DOWNLOAD_RETRIES,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max(0, max_retries)

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
        access_token = _require_access_token(decrypted_credential)
        workspace_id = _workspace_id(decrypted_credential)
        include_comments = bool(decrypted_credential.get("include_comments", False))

        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None
        effective_size = max(1, min(page_size, _MAX_PAGE_SIZE))

        scoped_pages = _scoped_page_ids(decrypted_credential, provider_source_id)
        scoped_dbs = _scoped_database_ids(decrypted_credential)

        if scoped_pages or scoped_dbs:
            return await self._list_scoped_items(
                access_token=access_token,
                scoped_page_ids=scoped_pages or [],
                scoped_db_ids=scoped_dbs or [],
                cursor=cursor,
                page_size=effective_size,
                organization_id=org_uuid,
                connection_id=conn_uuid,
                external_source_id=ext_src_uuid,
                workspace_id=workspace_id,
                include_comments=include_comments,
            )

        return await self._search_items(
            access_token=access_token,
            cursor=cursor,
            page_size=effective_size,
            organization_id=org_uuid,
            connection_id=conn_uuid,
            external_source_id=ext_src_uuid,
            workspace_id=workspace_id,
            include_comments=include_comments,
            include_archived=False,
        )

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
        access_token = _require_access_token(decrypted_credential)
        workspace_id = _workspace_id(decrypted_credential)
        include_comments = bool(decrypted_credential.get("include_comments", False))

        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None
        effective_size = max(1, min(page_size, _MAX_PAGE_SIZE))

        # Delta re-uses the search scan but includes archived pages so the engine
        # can tombstone them.  Content-hash comparison in the engine skips unchanged items.
        since = cursor.get("since")
        scan_cursor: dict[str, Any] = {"start_cursor": cursor.get("start_cursor")}

        item_page = await self._search_items(
            access_token=access_token,
            cursor=scan_cursor,
            page_size=effective_size,
            organization_id=org_uuid,
            connection_id=conn_uuid,
            external_source_id=ext_src_uuid,
            workspace_id=workspace_id,
            include_comments=include_comments,
            include_archived=True,
        )

        delta_items: list[DeltaItem] = []
        for item in item_page.items:
            is_deleted = bool(item.metadata.get("archived"))
            delta_items.append(
                DeltaItem(
                    provider_item_id=item.provider_item_id,
                    is_deleted=is_deleted,
                    item=item if not is_deleted else None,
                )
            )

        now_iso = datetime.now(UTC).isoformat()
        if item_page.has_more:
            next_cursor: dict[str, Any] = {
                "start_cursor": (item_page.next_cursor or {}).get("start_cursor"),
                "since": since or now_iso,
            }
        else:
            next_cursor = {"start_cursor": None, "since": now_iso}

        return DeltaPage(
            items=delta_items,
            next_cursor=next_cursor,
            has_more=item_page.has_more,
        )

    async def fetch_attachments(
        self,
        *,
        provider_item_id: str,
        decrypted_credential: dict,
    ) -> list[NormalizedExternalItem]:
        if not bool(decrypted_credential.get("include_attachments", False)):
            return []

        access_token = _require_access_token(decrypted_credential)
        org_id = decrypted_credential.get("_organization_id")
        conn_id = decrypted_credential.get("_connection_id")
        if not org_id or not conn_id:
            return []

        try:
            org_uuid = UUID(org_id)
            conn_uuid = UUID(conn_id)
        except ValueError:
            return []

        try:
            blocks = await self._get_block_children(
                access_token=access_token,
                block_id=provider_item_id,
                max_results=50,
            )
        except (ConnectorContentError, ConnectorProviderUnavailableError):
            return []

        page_url = f"https://www.notion.so/{provider_item_id.replace('-', '')}"
        return [
            normalize_file_block(
                block,
                page_id=provider_item_id,
                page_url=page_url,
                organization_id=org_uuid,
                connection_id=conn_uuid,
                external_source_id=None,
                sync_version=1,
            )
            for block in blocks
            if block.get("type") in NOTION_FILE_BLOCK_TYPES
        ]

    async def download_file_content(
        self,
        *,
        provider_item_id: str,
        mime_type: str | None,
        decrypted_credential: dict,
    ) -> tuple[bytes, str, str] | None:
        access_token = _require_access_token(decrypted_credential)

        # Attachment block download: provider_item_id = "block:<block_id>"
        if provider_item_id.startswith("block:"):
            block_id = provider_item_id[len("block:"):]
            return await self._download_block_file(
                access_token=access_token,
                block_id=block_id,
            )

        # Page content: render block tree to plain text
        max_depth = min(
            int(decrypted_credential.get("max_page_depth") or _DEFAULT_MAX_DEPTH),
            _MAX_BLOCK_FETCH_DEPTH,
        )
        return await self._render_page_to_text(
            access_token=access_token,
            page_id=provider_item_id,
            max_depth=max_depth,
        )

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    async def _search_items(
        self,
        *,
        access_token: str,
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        workspace_id: str | None,
        include_comments: bool,
        include_archived: bool,
    ) -> ItemPage:
        body: dict[str, Any] = {
            "page_size": page_size,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        }
        start_cursor = cursor.get("start_cursor")
        if start_cursor:
            body["start_cursor"] = start_cursor

        data = await self._post_json(
            access_token=access_token,
            path="/search",
            body=body,
        )

        items: list[NormalizedExternalItem] = []
        for result in data.get("results") or []:
            obj_type = result.get("object")
            archived = result.get("archived", False)
            if archived and not include_archived:
                continue

            if obj_type == "page":
                items.append(
                    normalize_page(
                        result,
                        organization_id=organization_id,
                        connection_id=connection_id,
                        external_source_id=external_source_id,
                        workspace_id=workspace_id,
                        sync_version=1,
                    )
                )
                if include_comments and not archived:
                    items.extend(
                        await self._fetch_page_comments(
                            access_token=access_token,
                            page_id=result["id"],
                            page_url=str(result.get("url") or ""),
                            organization_id=organization_id,
                            connection_id=connection_id,
                            external_source_id=external_source_id,
                        )
                    )
            elif obj_type == "database":
                items.append(
                    normalize_database(
                        result,
                        organization_id=organization_id,
                        connection_id=connection_id,
                        external_source_id=external_source_id,
                        workspace_id=workspace_id,
                        sync_version=1,
                    )
                )

        next_notion_cursor = data.get("next_cursor")
        has_more = bool(data.get("has_more"))
        next_cursor = {"start_cursor": next_notion_cursor} if has_more else None
        return ItemPage(items=items, next_cursor=next_cursor, has_more=has_more)

    async def _list_scoped_items(
        self,
        *,
        access_token: str,
        scoped_page_ids: list[str],
        scoped_db_ids: list[str],
        cursor: dict,
        page_size: int,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
        workspace_id: str | None,
        include_comments: bool,
    ) -> ItemPage:
        page_index = int(cursor.get("page_index", 0))
        db_index = int(cursor.get("db_index", 0))
        items: list[NormalizedExternalItem] = []

        while page_index < len(scoped_page_ids) and len(items) < page_size:
            pid = scoped_page_ids[page_index]
            try:
                page = await self._get_json(access_token=access_token, path=f"/pages/{pid}")
                if not page.get("archived", False):
                    items.append(
                        normalize_page(
                            page,
                            organization_id=organization_id,
                            connection_id=connection_id,
                            external_source_id=external_source_id,
                            workspace_id=workspace_id,
                            sync_version=1,
                        )
                    )
                    if include_comments:
                        items.extend(
                            await self._fetch_page_comments(
                                access_token=access_token,
                                page_id=pid,
                                page_url=str(page.get("url") or ""),
                                organization_id=organization_id,
                                connection_id=connection_id,
                                external_source_id=external_source_id,
                            )
                        )
            except ConnectorContentError:
                pass
            page_index += 1

        while db_index < len(scoped_db_ids) and len(items) < page_size:
            did = scoped_db_ids[db_index]
            try:
                db = await self._get_json(access_token=access_token, path=f"/databases/{did}")
                if not db.get("archived", False):
                    items.append(
                        normalize_database(
                            db,
                            organization_id=organization_id,
                            connection_id=connection_id,
                            external_source_id=external_source_id,
                            workspace_id=workspace_id,
                            sync_version=1,
                        )
                    )
            except ConnectorContentError:
                pass
            db_index += 1

        has_more = page_index < len(scoped_page_ids) or db_index < len(scoped_db_ids)
        next_cursor = {"page_index": page_index, "db_index": db_index} if has_more else None
        return ItemPage(items=items, next_cursor=next_cursor, has_more=has_more)

    async def _fetch_page_comments(
        self,
        *,
        access_token: str,
        page_id: str,
        page_url: str,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
    ) -> list[NormalizedExternalItem]:
        try:
            data = await self._get_json(
                access_token=access_token,
                path="/comments",
                params={"block_id": page_id, "page_size": 25},
            )
        except (ConnectorContentError, ConnectorProviderUnavailableError):
            return []

        url = page_url or f"https://www.notion.so/{page_id.replace('-', '')}"
        return [
            normalize_comment(
                c,
                page_id=page_id,
                page_url=url,
                organization_id=organization_id,
                connection_id=connection_id,
                external_source_id=external_source_id,
                sync_version=1,
            )
            for c in (data.get("results") or [])
            if isinstance(c, dict)
        ]

    async def _get_block_children(
        self,
        *,
        access_token: str,
        block_id: str,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        data = await self._get_json(
            access_token=access_token,
            path=f"/blocks/{block_id}/children",
            params={"page_size": min(max_results, _MAX_PAGE_SIZE)},
        )
        return [b for b in (data.get("results") or []) if isinstance(b, dict)]

    async def _render_page_to_text(
        self,
        *,
        access_token: str,
        page_id: str,
        max_depth: int,
    ) -> tuple[bytes, str, str] | None:
        blocks = await self._collect_blocks_recursive(
            access_token=access_token,
            block_id=page_id,
            current_depth=0,
            max_depth=max_depth,
        )
        if not blocks:
            return None
        text = render_blocks_to_text(blocks)
        if not text.strip():
            return None
        return text.encode("utf-8"), f"{page_id}.txt", "text/plain"

    async def _collect_blocks_recursive(
        self,
        *,
        access_token: str,
        block_id: str,
        current_depth: int,
        max_depth: int,
    ) -> list[dict[str, Any]]:
        if current_depth > max_depth:
            return []

        data = await self._get_json(
            access_token=access_token,
            path=f"/blocks/{block_id}/children",
            params={"page_size": _MAX_PAGE_SIZE},
        )
        blocks: list[dict[str, Any]] = [
            b for b in (data.get("results") or []) if isinstance(b, dict)
        ]

        # Paginate within this block level
        has_more = bool(data.get("has_more"))
        next_cursor = data.get("next_cursor")
        while has_more and next_cursor:
            extra_data = await self._get_json(
                access_token=access_token,
                path=f"/blocks/{block_id}/children",
                params={"page_size": _MAX_PAGE_SIZE, "start_cursor": next_cursor},
            )
            blocks.extend(
                b for b in (extra_data.get("results") or []) if isinstance(b, dict)
            )
            has_more = bool(extra_data.get("has_more"))
            next_cursor = extra_data.get("next_cursor")

        # Recursively attach children for blocks that have them
        if current_depth < max_depth:
            for block in blocks:
                if block.get("has_children"):
                    block["_children"] = await self._collect_blocks_recursive(
                        access_token=access_token,
                        block_id=block["id"],
                        current_depth=current_depth + 1,
                        max_depth=max_depth,
                    )

        return blocks

    async def _download_block_file(
        self,
        *,
        access_token: str,
        block_id: str,
    ) -> tuple[bytes, str, str] | None:
        block = await self._get_json(
            access_token=access_token,
            path=f"/blocks/{block_id}",
        )
        block_type = block.get("type", "")
        if block_type not in NOTION_FILE_BLOCK_TYPES:
            return None

        file_obj = block.get(block_type) or {}
        hosted_url = (file_obj.get("file") or {}).get("url", "")
        external_url = (file_obj.get("external") or {}).get("url", "")
        url = hosted_url or external_url
        if not url.startswith("http"):
            return None

        file_name = file_obj.get("name") or f"{block_type}-{block_id}"
        if "." not in file_name:
            ext = ".pdf" if block_type == "pdf" else ".bin"
            file_name = f"{file_name}{ext}"

        mime_type = "application/pdf" if block_type == "pdf" else "application/octet-stream"
        content = await self._download_bytes(url)
        return content, file_name, mime_type

    # ------------------------------------------------------------------
    # HTTP primitives
    # ------------------------------------------------------------------

    async def _post_json(
        self,
        *,
        access_token: str,
        path: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{_NOTION_API_BASE}{path}",
                        json=body,
                        headers=_auth_headers(access_token),
                    )
                _raise_for_status(response)
                data = response.json()
                if not isinstance(data, dict):
                    raise ConnectorProviderUnavailableError("Notion API returned an invalid payload")
                return data
            except (ConnectorRateLimitError, ConnectorAuthError, ConnectorContentError):
                raise
            except (httpx.TimeoutException, ConnectorProviderUnavailableError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 4))
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 4))
        if isinstance(last_exc, ConnectorProviderUnavailableError):
            raise last_exc
        raise ConnectorProviderUnavailableError("Notion API POST request failed")

    async def _get_json(
        self,
        *,
        access_token: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(
                        f"{_NOTION_API_BASE}{path}",
                        params=params,
                        headers=_auth_headers(access_token),
                    )
                _raise_for_status(response)
                data = response.json()
                if not isinstance(data, dict):
                    raise ConnectorProviderUnavailableError("Notion API returned an invalid payload")
                return data
            except (ConnectorRateLimitError, ConnectorAuthError, ConnectorContentError):
                raise
            except (httpx.TimeoutException, ConnectorProviderUnavailableError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 4))
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 4))
        if isinstance(last_exc, ConnectorProviderUnavailableError):
            raise last_exc
        raise ConnectorProviderUnavailableError("Notion API GET request failed")

    async def _download_bytes(self, url: str) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, follow_redirects=True
                ) as client:
                    response = await client.get(url)
                if response.status_code == 429:
                    retry_after = parse_retry_after(dict(response.headers))
                    raise ConnectorRateLimitError(
                        "Rate limited downloading Notion file",
                        retry_after_seconds=retry_after,
                    )
                response.raise_for_status()
                return response.content
            except ConnectorRateLimitError:
                raise
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt, 4))
        raise ConnectorProviderUnavailableError("Notion file download failed")


__all__ = ["NotionConnectorAdapter"]
