"""Confluence Cloud connector adapter.

Implements the ConnectorProviderAdapter contract using the Confluence Cloud REST API v1.

Credential dict shape (OAuth2, stored in decrypted_credential):
    {
        "auth_type": "oauth2",
        "access_token": "<token>",
        "refresh_token": "<token>",         # optional
        "site_url": "https://mysite.atlassian.net",  # required
        "space_keys": ["SPACE1", "SPACE2"], # optional – if omitted, all spaces
        "cql_filter": 'label = "docs"',     # optional extra CQL predicate
        "include_comments": true,           # optional – default False (avoids N+1 calls)
    }

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

_CONFLUENCE_EXPAND = (
    "body.storage,version,space,ancestors,metadata.labels,history"
)
_COMMENT_EXPAND = "body.storage,version"
_ATTACHMENT_EXPAND = "version"
_DEFAULT_TIMEOUT = 30.0
_MAX_COMMENTS_PER_PAGE = 25


def _require_site_url(credential: dict[str, Any]) -> str:
    site_url = (credential.get("site_url") or "").strip().rstrip("/")
    if not site_url:
        raise ConnectorContentError(
            "Confluence credential is missing 'site_url'. "
            "Re-authorize the connection and include the Confluence site URL."
        )
    return site_url


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
    """Confluence Cloud adapter: full sync + delta sync via CQL, optional comments and attachments."""

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
        """Full sync: fetch all pages matching the configured CQL."""
        site_url = _require_site_url(decrypted_credential)
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
            site_url=site_url,
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
                        site_url=site_url,
                        access_token=access_token,
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
        site_url = _require_site_url(decrypted_credential)
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
            site_url=site_url,
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
            delta_items.append(DeltaItem(
                provider_item_id=page_item.provider_item_id,
                is_deleted=False,
                item=page_item,
            ))

            if include_comments:
                for comment_item in await self._extract_comments(
                    page,
                    site_url=site_url,
                    access_token=access_token,
                    organization_id=org_uuid,
                    connection_id=conn_uuid,
                    external_source_id=ext_src_uuid,
                ):
                    delta_items.append(DeltaItem(
                        provider_item_id=comment_item.provider_item_id,
                        is_deleted=False,
                        item=comment_item,
                    ))

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
            next_cursor=new_cursor if has_next else {
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
        site_url = _require_site_url(decrypted_credential)
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
            site_url=site_url,
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

    # ------------------------------------------------------------------
    # Private HTTP helpers
    # ------------------------------------------------------------------

    async def _search_pages(
        self,
        *,
        site_url: str,
        access_token: str,
        cql: str,
        start: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return (pages, has_next) from a CQL content search."""
        url = f"{site_url}/wiki/rest/api/content/search"
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
        has_next = "_links" in data and "next" in (data.get("_links") or {})
        return pages, has_next

    async def _get_page_attachments(
        self,
        *,
        site_url: str,
        access_token: str,
        page_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        url = f"{site_url}/wiki/rest/api/content/{page_id}/child/attachment"
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
        site_url: str,
        access_token: str,
        page_id: str,
        limit: int = _MAX_COMMENTS_PER_PAGE,
    ) -> list[dict[str, Any]]:
        url = f"{site_url}/wiki/rest/api/content/{page_id}/child/comment"
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
        site_url: str,
        access_token: str,
        organization_id: UUID,
        connection_id: UUID,
        external_source_id: UUID | None,
    ) -> list[NormalizedExternalItem]:
        page_id = page["id"]
        url = _page_url(site_url, page)
        comments = await self._get_page_comments(
            site_url=site_url,
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
