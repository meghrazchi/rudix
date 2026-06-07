"""Jira Cloud connector adapter.

Implements the ConnectorProviderAdapter contract using the Jira Cloud REST API v3.

Credential dict shape (OAuth2, stored in decrypted_credential):
    {
        "auth_type": "oauth2",
        "access_token": "<token>",
        "refresh_token": "<token>",      # optional
        "site_url": "https://mysite.atlassian.net",  # required
        "project_keys": ["PROJ", "WEB"], # optional – if omitted, all projects
        "jql_filter": "status != Done",  # optional extra JQL predicate
    }

Cursor shape for full sync:    {"start_at": 0}
Cursor shape for delta sync:   {"since": "2024-01-01T00:00:00+00:00", "start_at": 0}
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx

from app.domains.connectors.providers.jira.normalizer import (
    normalize_attachment,
    normalize_comment,
    normalize_issue,
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

_JIRA_FIELDS = (
    "summary,description,status,priority,issuetype,project,"
    "assignee,reporter,labels,components,created,updated,"
    "comment,attachment"
)
_DEFAULT_TIMEOUT = 30.0
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _require_site_url(credential: dict[str, Any]) -> str:
    site_url = (credential.get("site_url") or "").strip().rstrip("/")
    if not site_url:
        raise ConnectorContentError(
            "Jira credential is missing 'site_url'. "
            "Re-authorize the connection and include the Jira site URL."
        )
    return site_url


def _bearer_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _build_jql(
    project_keys: list[str] | None,
    jql_filter: str | None,
    *,
    since: str | None = None,
) -> str:
    parts: list[str] = []

    if project_keys:
        keys_csv = ", ".join(f'"{k}"' for k in project_keys)
        parts.append(f"project in ({keys_csv})")

    if since:
        parts.append(f'updated >= "{since}"')

    if jql_filter:
        parts.append(f"({jql_filter})")

    base = " AND ".join(parts) if parts else "ORDER BY updated ASC"
    if parts:
        base += " ORDER BY updated ASC"
    return base


def _raise_for_status(response: httpx.Response) -> None:
    """Map Jira HTTP errors to connector error types."""
    raise_for_rate_limit(response.status_code, dict(response.headers))
    if response.status_code in (401, 403):
        raise ConnectorAuthError(
            f"Jira returned {response.status_code}: credential is invalid or has insufficient scope."
        )
    if response.status_code >= 500:
        raise ConnectorProviderUnavailableError(
            f"Jira returned {response.status_code}: provider unavailable."
        )
    response.raise_for_status()


class JiraConnectorAdapter(ConnectorProviderAdapter):
    """Jira Cloud adapter: full sync + delta sync via JQL, comments and attachments."""

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
        """Full sync: fetch all issues matching the configured JQL."""
        site_url = _require_site_url(decrypted_credential)
        access_token = decrypted_credential.get("access_token", "")
        project_keys = _resolve_project_keys(provider_source_id, decrypted_credential)
        jql_filter = decrypted_credential.get("jql_filter")

        jql = _build_jql(project_keys, jql_filter)
        start_at = int(cursor.get("start_at", 0))

        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None

        issues, total = await self._search_issues(
            site_url=site_url,
            access_token=access_token,
            jql=jql,
            start_at=start_at,
            max_results=page_size,
        )

        items: list[NormalizedExternalItem] = []
        for issue in issues:
            issue_item = normalize_issue(
                issue,
                organization_id=org_uuid,
                connection_id=conn_uuid,
                external_source_id=ext_src_uuid,
                site_url=site_url,
                sync_version=1,
            )
            items.append(issue_item)
            items.extend(
                _extract_comments(
                    issue,
                    organization_id=org_uuid,
                    connection_id=conn_uuid,
                    external_source_id=ext_src_uuid,
                    site_url=site_url,
                    sync_version=1,
                )
            )

        next_start = start_at + len(issues)
        has_more = next_start < total and len(issues) > 0
        return ItemPage(
            items=items,
            next_cursor={"start_at": next_start} if has_more else None,
            has_more=has_more,
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
        """Incremental sync: fetch issues updated since cursor['since']."""
        site_url = _require_site_url(decrypted_credential)
        access_token = decrypted_credential.get("access_token", "")
        project_keys = _resolve_project_keys(provider_source_id, decrypted_credential)
        jql_filter = decrypted_credential.get("jql_filter")

        since = cursor.get("since")
        start_at = int(cursor.get("start_at", 0))
        jql = _build_jql(project_keys, jql_filter, since=since)

        org_uuid = UUID(organization_id)
        conn_uuid = UUID(connection_id)
        ext_src_uuid = UUID(external_source_id) if external_source_id else None

        issues, total = await self._search_issues(
            site_url=site_url,
            access_token=access_token,
            jql=jql,
            start_at=start_at,
            max_results=page_size,
        )

        delta_items: list[DeltaItem] = []
        latest_updated = since

        for issue in issues:
            issue_item = normalize_issue(
                issue,
                organization_id=org_uuid,
                connection_id=conn_uuid,
                external_source_id=ext_src_uuid,
                site_url=site_url,
                sync_version=1,
            )
            delta_items.append(
                DeltaItem(
                    provider_item_id=issue_item.provider_item_id,
                    is_deleted=False,
                    item=issue_item,
                )
            )

            for comment_item in _extract_comments(
                issue,
                organization_id=org_uuid,
                connection_id=conn_uuid,
                external_source_id=ext_src_uuid,
                site_url=site_url,
                sync_version=1,
            ):
                delta_items.append(
                    DeltaItem(
                        provider_item_id=comment_item.provider_item_id,
                        is_deleted=False,
                        item=comment_item,
                    )
                )

            updated_field = (issue.get("fields") or {}).get("updated", "")
            if updated_field and (latest_updated is None or updated_field > latest_updated):
                latest_updated = updated_field

        next_start = start_at + len(issues)
        has_more = next_start < total and len(issues) > 0

        new_cursor: dict[str, Any] = {
            "since": latest_updated or datetime.now(UTC).isoformat(),
            "start_at": next_start if has_more else 0,
        }
        return DeltaPage(
            items=delta_items,
            next_cursor=new_cursor
            if has_more
            else {
                "since": new_cursor["since"],
                "start_at": 0,
            },
            has_more=has_more,
        )

    async def fetch_attachments(
        self,
        *,
        provider_item_id: str,
        decrypted_credential: dict,
    ) -> list[NormalizedExternalItem]:
        """Fetch attachment items for a Jira issue.

        *provider_item_id* is the issue key (e.g. "PROJ-1").
        Returns NormalizedExternalItem records for each attachment.
        """
        site_url = _require_site_url(decrypted_credential)
        access_token = decrypted_credential.get("access_token", "")

        issue = await self._get_issue(
            site_url=site_url,
            access_token=access_token,
            issue_key=provider_item_id,
            fields="attachment,summary,updated",
        )
        attachments = (issue.get("fields") or {}).get("attachment") or []

        org_id = decrypted_credential.get("_organization_id")
        conn_id = decrypted_credential.get("_connection_id")
        if not org_id or not conn_id:
            return []

        try:
            org_uuid = UUID(org_id)
            conn_uuid = UUID(conn_id)
        except ValueError:
            return []

        return [
            normalize_attachment(
                att,
                issue_key=provider_item_id,
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

    async def _search_issues(
        self,
        *,
        site_url: str,
        access_token: str,
        jql: str,
        start_at: int,
        max_results: int,
    ) -> tuple[list[dict[str, Any]], int]:
        url = f"{site_url}/rest/api/3/search"
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": max_results,
            "fields": _JIRA_FIELDS,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                url,
                params=params,
                headers=_bearer_headers(access_token),
            )
        _raise_for_status(response)
        data = response.json()
        return data.get("issues", []), data.get("total", 0)

    async def _get_issue(
        self,
        *,
        site_url: str,
        access_token: str,
        issue_key: str,
        fields: str = _JIRA_FIELDS,
    ) -> dict[str, Any]:
        url = f"{site_url}/rest/api/3/issue/{issue_key}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                url,
                params={"fields": fields},
                headers=_bearer_headers(access_token),
            )
        _raise_for_status(response)
        return response.json()


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _resolve_project_keys(
    provider_source_id: str | None,
    credential: dict[str, Any],
) -> list[str] | None:
    """Resolve which Jira project keys to sync.

    Priority: provider_source_id (per-source sync) > credential.project_keys > None (all).
    """
    if provider_source_id:
        return [provider_source_id]
    keys = credential.get("project_keys")
    if isinstance(keys, list) and keys:
        return [str(k).strip() for k in keys if str(k).strip()]
    return None


def _extract_comments(
    issue: dict[str, Any],
    *,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    site_url: str,
    sync_version: int,
) -> list[NormalizedExternalItem]:
    """Extract embedded comments from a Jira issue response."""
    issue_key = issue["key"]
    comment_block = (issue.get("fields") or {}).get("comment") or {}
    comments = comment_block.get("comments") or []
    return [
        normalize_comment(
            c,
            issue_key=issue_key,
            organization_id=organization_id,
            connection_id=connection_id,
            external_source_id=external_source_id,
            site_url=site_url,
            sync_version=sync_version,
        )
        for c in comments
    ]
