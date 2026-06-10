"""Confluence Cloud connector adapter.

Implements the ConnectorProviderAdapter contract using the Confluence Cloud REST API v1
via the Atlassian OAuth 2.0 (3LO) gateway at api.atlassian.com.

Credential dict shape (OAuth2, stored in decrypted_credential):
    {
        "auth_type": "oauth2",
        "access_token": "<token>",
        "refresh_token": "<token>",               # optional
        "cloud_id": "1324a887-45db-...",          # required — set at OAuth callback time
        "site_url": "https://myteam.atlassian.net",  # for human-readable page URLs
        "space_keys": ["SPACE1", "SPACE2"],       # optional – if omitted, all spaces
        "cql_filter": 'label = "docs"',           # optional extra CQL predicate
        "include_comments": true,                 # optional – default False
    }

cloud_id is discovered automatically via the accessible-resources endpoint during the
OAuth callback and stored in credential metadata.  All Confluence API calls go through
https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/rest/api/...

Cursor shape for full sync:    {"start": 0}
Cursor shape for delta sync:   {"since": "2024-01-01T00:00:00+00:00", "start": 0}
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from app.domains.connectors.providers.confluence.normalizer import (
    _page_url,
    _storage_html_to_text,
    normalize_attachment,
    normalize_comment,
    normalize_page,
)
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
from app.domains.connectors.schemas.connectors import NormalizedExternalItem

_ATLASSIAN_API_BASE = "https://api.atlassian.com/ex/confluence"
_CONFLUENCE_EXPAND = "body.storage,version,space,ancestors,metadata.labels,history"
_COMMENT_EXPAND = "body.storage,version"
_ATTACHMENT_EXPAND = "version"
_DEFAULT_TIMEOUT = 30.0
_MAX_COMMENTS_PER_PAGE = 25


def _require_cloud_id(credential: dict[str, Any]) -> str:
    cloud_id = (credential.get("cloud_id") or "").strip()
    if not cloud_id:
        raise ConnectorAuthError(
            "Confluence credential is missing 'cloud_id'. "
            "Re-authorize the connection to allow Rudix to discover your Confluence site."
        )
    return cloud_id


def _api_base(cloud_id: str) -> str:
    return f"{_ATLASSIAN_API_BASE}/{cloud_id}/wiki/rest/api"


def _site_url_for_display(credential: dict[str, Any], cloud_id: str) -> str:
    """Return a site URL suitable for building human-readable page links."""
    site_url = (credential.get("site_url") or "").strip().rstrip("/")
    if site_url:
        return site_url
    return f"https://api.atlassian.com/ex/confluence/{cloud_id}"


def _bearer_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _build_cql(
    space_keys: list[str] | None,
    cql_filter: str | None,
    *,
    since: str | None = None,
) -> str:
    parts: list[str] = ['type = "page"']

    if space_keys:
        keys_csv = ", ".join(f'"{k}"' for k in space_keys)
        parts.append(f"space.key in ({keys_csv})")

    if since:
        parts.append(f'lastModified >= "{since}"')

    if cql_filter:
        parts.append(f"({cql_filter})")

    return " AND ".join(parts) + " ORDER BY lastModified ASC"


def _raise_for_status(response: httpx.Response) -> None:
    """Map Confluence HTTP errors to connector error types."""
    raise_for_rate_limit(response.status_code, dict(response.headers))
    if response.status_code in (401, 403):
        raise ConnectorAuthError(
            f"Confluence returned {response.status_code}: credential is invalid or has insufficient scope."
        )
    if response.status_code >= 500:
        raise ConnectorProviderUnavailableError(
            f"Confluence returned {response.status_code}: provider unavailable."
        )
    response.raise_for_status()


def _resolve_space_keys(
    provider_source_id: str | None,
    credential: dict[str, Any],
) -> list[str] | None:
    """Resolve which Confluence space keys to sync.

    Priority: provider_source_id (per-source sync) > credential.space_keys > None (all).
    """
    if provider_source_id:
        return [provider_source_id]
    keys = credential.get("space_keys")
    if isinstance(keys, list) and keys:
        return [str(k).strip() for k in keys if str(k).strip()]
    return None


class ConfluenceConnectorAdapter(ConnectorProviderAdapter):
    """Confluence Cloud adapter: full sync + delta sync via CQL, optional comments and attachments.

    All API calls use the Atlassian OAuth 2.0 (3LO) gateway:
        https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/rest/api/...
    """

    def __init__(self, *, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        # Cache page bodies fetched during list_items/delta_sync so
        # download_file_content can return them without a second HTTP call.
        # Confluence Cloud's v1 GET /content/{id} returns 410 for some pages
        # even though the CQL search endpoint serves them fine.
        self._page_body_cache: dict[str, tuple[str, str]] = {}  # page_id -> (body_text, title)

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
        """Full sync: fetch all pages matching the configured CQL."""
        cloud_id = _require_cloud_id(decrypted_credential)
        site_url = _site_url_for_display(decrypted_credential, cloud_id)
        access_token = decrypted_credential.get("access_token", "")
        space_keys = _resolve_space_keys(provider_source_id, decrypted_credential)
        cql_filter = decrypted_credential.get("cql_filter")
        include_comments = bool(decrypted_credential.get("include_comments", False))

        cql = _build_cql(space_keys, cql_filter)
        start = int(cursor.get("start", 0))

        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None

        pages, has_next = await self._search_pages(
            cloud_id=cloud_id,
            access_token=access_token,
            cql=cql,
            start=start,
            limit=page_size,
        )

        items: list[NormalizedExternalItem] = []
        for page in pages:
            page_item = normalize_page(
                page,
                organization_id=org_uuid,
                connection_id=conn_uuid,
                external_source_id=ext_src_uuid,
                site_url=site_url,
                sync_version=1,
            )
            items.append(page_item)

            if include_comments:
                items.extend(
                    await self._extract_comments(
                        page,
                        cloud_id=cloud_id,
                        access_token=access_token,
                        site_url=site_url,
                        organization_id=org_uuid,
                        connection_id=conn_uuid,
                        external_source_id=ext_src_uuid,
                    )
                )

        next_start = start + len(pages)
        return ItemPage(
            items=items,
            next_cursor={"start": next_start} if has_next else None,
            has_more=has_next,
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
        """Incremental sync: fetch pages modified since cursor['since']."""
        cloud_id = _require_cloud_id(decrypted_credential)
        site_url = _site_url_for_display(decrypted_credential, cloud_id)
        access_token = decrypted_credential.get("access_token", "")
        space_keys = _resolve_space_keys(provider_source_id, decrypted_credential)
        cql_filter = decrypted_credential.get("cql_filter")
        include_comments = bool(decrypted_credential.get("include_comments", False))

        since = cursor.get("since")
        start = int(cursor.get("start", 0))
        cql = _build_cql(space_keys, cql_filter, since=since)

        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None

        pages, has_next = await self._search_pages(
            cloud_id=cloud_id,
            access_token=access_token,
            cql=cql,
            start=start,
            limit=page_size,
        )

        delta_items: list[DeltaItem] = []
        latest_modified = since

        for page in pages:
            page_item = normalize_page(
                page,
                organization_id=org_uuid,
                connection_id=conn_uuid,
                external_source_id=ext_src_uuid,
                site_url=site_url,
                sync_version=1,
            )
            delta_items.append(
                DeltaItem(
                    provider_item_id=page_item.provider_item_id,
                    is_deleted=False,
                    item=page_item,
                )
            )

            if include_comments:
                for comment_item in await self._extract_comments(
                    page,
                    cloud_id=cloud_id,
                    access_token=access_token,
                    site_url=site_url,
                    organization_id=org_uuid,
                    connection_id=conn_uuid,
                    external_source_id=ext_src_uuid,
                ):
                    delta_items.append(
                        DeltaItem(
                            provider_item_id=comment_item.provider_item_id,
                            is_deleted=False,
                            item=comment_item,
                        )
                    )

            last_modified_field = (page.get("version") or {}).get("when", "")
            if last_modified_field and (
                latest_modified is None or last_modified_field > latest_modified
            ):
                latest_modified = last_modified_field

        next_start = start + len(pages)
        new_cursor: dict[str, Any] = {
            "since": latest_modified or datetime.now(UTC).isoformat(),
            "start": next_start if has_next else 0,
        }
        return DeltaPage(
            items=delta_items,
            next_cursor=new_cursor
            if has_next
            else {
                "since": new_cursor["since"],
                "start": 0,
            },
            has_more=has_next,
        )

    async def fetch_attachments(
        self,
        *,
        provider_item_id: str,
        decrypted_credential: dict,
    ) -> list[NormalizedExternalItem]:
        """Fetch attachment items for a Confluence page.

        *provider_item_id* is the page ID (numeric string, e.g. "123456").
        Returns NormalizedExternalItem records for each attachment.
        """
        cloud_id = _require_cloud_id(decrypted_credential)
        site_url = _site_url_for_display(decrypted_credential, cloud_id)
        access_token = decrypted_credential.get("access_token", "")

        org_id = decrypted_credential.get("_organization_id")
        conn_id = decrypted_credential.get("_connection_id")
        if not org_id or not conn_id:
            return []

        try:
            org_uuid = UUID(org_id)
            conn_uuid = UUID(conn_id)
        except ValueError:
            return []

        attachments = await self._get_page_attachments(
            cloud_id=cloud_id,
            access_token=access_token,
            page_id=provider_item_id,
        )

        return [
            normalize_attachment(
                att,
                page_id=provider_item_id,
                organization_id=org_uuid,
                connection_id=conn_uuid,
                external_source_id=None,
                site_url=site_url,
                sync_version=1,
            )
            for att in attachments
        ]

    async def download_file_content(
        self,
        *,
        provider_item_id: str,
        mime_type: str | None,
        decrypted_credential: dict,
    ) -> tuple[bytes, str, str] | None:
        """Return a Confluence page body as plain text bytes.

        Prefers the body already cached from list_items/delta_sync to avoid a
        second HTTP call. Confluece Cloud's v1 GET /content/{id} returns 410
        for some pages even though the CQL search endpoint serves them fine.
        Falls back to an API fetch only on a cache miss (e.g. test scenarios).
        """
        del mime_type
        cached = self._page_body_cache.pop(provider_item_id, None)
        if cached is not None:
            body_text, title = cached
            if not body_text.strip():
                return None
            filename = f"{title[:200]}.txt"
            return body_text.encode("utf-8"), filename, "text/plain"

        # Cache miss: fetch the page body directly.
        cloud_id = _require_cloud_id(decrypted_credential)
        access_token = decrypted_credential.get("access_token", "")
        url = f"{_api_base(cloud_id)}/content/{provider_item_id}"
        params = {"expand": "body.storage,title,version,space"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                url,
                params=params,
                headers=_bearer_headers(access_token),
            )
        _raise_for_status(response)
        page = response.json()
        title = page.get("title") or provider_item_id
        body_html = (page.get("body") or {}).get("storage", {}).get("value", "")
        body_text = _storage_html_to_text(body_html)
        if not body_text.strip():
            return None
        filename = f"{title[:200]}.txt"
        return body_text.encode("utf-8"), filename, "text/plain"

    def _cache_page_body(self, page: dict[str, Any]) -> None:
        page_id = page.get("id", "")
        if not page_id:
            return
        body_html = (page.get("body") or {}).get("storage", {}).get("value", "")
        body_text = _storage_html_to_text(body_html)
        title = page.get("title") or page_id
        self._page_body_cache[page_id] = (body_text, title)

    # ------------------------------------------------------------------
    # Private HTTP helpers
    # ------------------------------------------------------------------

    async def _search_pages(
        self,
        *,
        cloud_id: str,
        access_token: str,
        cql: str,
        start: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return (pages, has_next) from a CQL content search."""
        url = f"{_api_base(cloud_id)}/content/search"
        params = {
            "cql": cql,
            "start": start,
            "limit": limit,
            "expand": _CONFLUENCE_EXPAND,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                url,
                params=params,
                headers=_bearer_headers(access_token),
            )
        _raise_for_status(response)
        data = response.json()
        pages = data.get("results", [])
        for page in pages:
            self._cache_page_body(page)
        has_next = "_links" in data and "next" in (data.get("_links") or {})
        return pages, has_next

    async def _get_page_attachments(
        self,
        *,
        cloud_id: str,
        access_token: str,
        page_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        url = f"{_api_base(cloud_id)}/content/{page_id}/child/attachment"
        params = {"expand": _ATTACHMENT_EXPAND, "limit": limit}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                url,
                params=params,
                headers=_bearer_headers(access_token),
            )
        _raise_for_status(response)
        return response.json().get("results", [])

    async def _get_page_comments(
        self,
        *,
        cloud_id: str,
        access_token: str,
        page_id: str,
        limit: int = _MAX_COMMENTS_PER_PAGE,
    ) -> list[dict[str, Any]]:
        url = f"{_api_base(cloud_id)}/content/{page_id}/child/comment"
        params = {"expand": _COMMENT_EXPAND, "limit": limit}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                url,
                params=params,
                headers=_bearer_headers(access_token),
            )
        _raise_for_status(response)
        return response.json().get("results", [])

    async def _extract_comments(
        self,
        page: dict[str, Any],
        *,
        cloud_id: str,
        access_token: str,
        site_url: str,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
    ) -> list[NormalizedExternalItem]:
        page_id = page["id"]
        url = _page_url(site_url, page)
        comments = await self._get_page_comments(
            cloud_id=cloud_id,
            access_token=access_token,
            page_id=page_id,
        )
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
            for c in comments
        ]
