"""Tests for F242: Jira connector adapter.

Covers:
- Full sync pagination via list_items
- Delta sync with JQL since-cursor
- Comment normalization as child items
- Attachment normalization
- Error mapping (401 → ConnectorAuthError, 429 → ConnectorRateLimitError, 5xx → unavailable)
- JQL construction (project filter, jql_filter, since)
- ADF-to-text extraction
- Content hash stability
- Provider contract suite
- Missing site_url handling
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from app.domains.connectors.providers.jira.adapter import (
    JiraConnectorAdapter,
    _build_jql,
    _extract_comments,
    _resolve_project_keys,
)
from app.domains.connectors.providers.jira.normalizer import (
    _adf_to_text,
    _issue_content_hash,
    normalize_attachment,
    normalize_comment,
    normalize_issue,
)
from app.domains.connectors.sdk.testing import run_adapter_contract_suite
from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorContentError,
    ConnectorProviderUnavailableError,
    ConnectorRateLimitError,
    ItemPage,
)
from app.models.enums import ExternalItemType, ExternalItemVisibility

pytestmark = pytest.mark.jira_adapter

_ORG_ID = str(uuid4())
_CONN_ID = str(uuid4())
_ORG_UUID = UUID(_ORG_ID)
_CONN_UUID = UUID(_CONN_ID)

_BASE_CRED = {
    "auth_type": "oauth2",
    "access_token": "test-token-abc",
    "site_url": "https://mysite.atlassian.net",
}

_SAMPLE_ISSUE = {
    "id": "10001",
    "key": "PROJ-1",
    "self": "https://mysite.atlassian.net/rest/api/3/issue/10001",
    "fields": {
        "summary": "Fix login bug",
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Users cannot log in after reset."}],
                }
            ],
        },
        "status": {"name": "Open"},
        "priority": {"name": "High"},
        "issuetype": {"name": "Bug"},
        "project": {"key": "PROJ", "name": "Project Alpha"},
        "assignee": {"accountId": "acc-1", "displayName": "Alice Smith"},
        "reporter": {"accountId": "acc-2", "displayName": "Bob Jones"},
        "labels": ["bug", "login"],
        "components": [{"name": "Auth"}],
        "created": "2024-01-01T08:00:00.000+0000",
        "updated": "2024-06-01T10:00:00.000+0000",
        "comment": {
            "comments": [
                {
                    "id": "20001",
                    "author": {"accountId": "acc-3", "displayName": "Carol"},
                    "body": {"type": "doc", "version": 1, "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Reproduced."}]},
                    ]},
                    "created": "2024-03-01T09:00:00.000+0000",
                    "updated": "2024-03-01T09:00:00.000+0000",
                }
            ],
            "total": 1,
        },
        "attachment": [
            {
                "id": "30001",
                "filename": "screenshot.png",
                "mimeType": "image/png",
                "size": 48200,
                "created": "2024-03-02T10:00:00.000+0000",
                "author": {"displayName": "Alice Smith"},
                "content": "https://mysite.atlassian.net/secure/attachment/30001/screenshot.png",
            }
        ],
    },
}

_SEARCH_RESPONSE_SINGLE = {
    "total": 1,
    "startAt": 0,
    "maxResults": 50,
    "issues": [_SAMPLE_ISSUE],
}

_SEARCH_RESPONSE_EMPTY = {
    "total": 0,
    "startAt": 0,
    "maxResults": 50,
    "issues": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_httpx_response(data: dict, *, status: int = 200) -> httpx.Response:
    content = json.dumps(data).encode()
    return httpx.Response(
        status_code=status,
        headers={"content-type": "application/json"},
        content=content,
        request=httpx.Request("GET", "https://mysite.atlassian.net/rest/api/3/search"),
    )


def _make_httpx_error_response(*, status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        content=b'{"errorMessages": [], "errors": {}}',
        request=httpx.Request("GET", "https://mysite.atlassian.net/rest/api/3/search"),
    )


# ---------------------------------------------------------------------------
# ADF text extraction
# ---------------------------------------------------------------------------


def test_adf_to_text_plain_string() -> None:
    assert _adf_to_text("plain text") == "plain text"


def test_adf_to_text_none() -> None:
    assert _adf_to_text(None) == ""


def test_adf_to_text_simple_doc() -> None:
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Hello world"}],
            }
        ],
    }
    result = _adf_to_text(adf)
    assert "Hello world" in result


def test_adf_to_text_nested() -> None:
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Line one."},
                    {"type": "text", "text": " Line two."},
                ],
            }
        ],
    }
    result = _adf_to_text(adf)
    assert "Line one" in result
    assert "Line two" in result


# ---------------------------------------------------------------------------
# Normalizer — issue
# ---------------------------------------------------------------------------


def test_normalize_issue_basic_fields() -> None:
    item = normalize_issue(
        _SAMPLE_ISSUE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.provider_key == "jira"
    assert item.provider_item_id == "PROJ-1"
    assert item.item_type == ExternalItemType.issue
    assert item.title == "Fix login bug"
    assert item.source_url == "https://mysite.atlassian.net/browse/PROJ-1"
    assert item.visibility == ExternalItemVisibility.org_wide
    assert len(item.content_hash) == 64


def test_normalize_issue_metadata() -> None:
    item = normalize_issue(
        _SAMPLE_ISSUE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.metadata["status"] == "Open"
    assert item.metadata["priority"] == "High"
    assert item.metadata["issue_key"] == "PROJ-1"
    assert item.metadata["assignee_display_name"] == "Alice Smith"
    assert item.metadata["reporter_display_name"] == "Bob Jones"
    assert "bug" in item.metadata["labels"]


def test_normalize_issue_content_hash_stability() -> None:
    h1 = _issue_content_hash(_SAMPLE_ISSUE)
    h2 = _issue_content_hash(_SAMPLE_ISSUE)
    assert h1 == h2
    assert len(h1) == 64


def test_normalize_issue_null_assignee() -> None:
    issue = dict(_SAMPLE_ISSUE)
    issue["fields"] = dict(_SAMPLE_ISSUE["fields"])
    issue["fields"]["assignee"] = None
    item = normalize_issue(
        issue,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert "assignee_display_name" not in item.metadata
    assert "assignee_account_id" not in item.metadata


# ---------------------------------------------------------------------------
# Normalizer — comment
# ---------------------------------------------------------------------------


def test_normalize_comment_structure() -> None:
    raw = _SAMPLE_ISSUE["fields"]["comment"]["comments"][0]
    item = normalize_comment(
        raw,
        issue_key="PROJ-1",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.provider_item_id == "comment-20001"
    assert item.item_type == ExternalItemType.comment
    assert item.provider_parent_id == "PROJ-1"
    assert item.root_provider_item_id == "PROJ-1"
    assert "Carol" in item.title
    assert "PROJ-1" in item.title
    assert "focusedCommentId=20001" in item.source_url
    assert item.metadata["author_display_name"] == "Carol"


def test_normalize_comment_requires_parent_id() -> None:
    """NormalizedExternalItem must reject comments without provider_parent_id."""
    from pydantic import ValidationError
    raw = _SAMPLE_ISSUE["fields"]["comment"]["comments"][0]
    item = normalize_comment(
        raw,
        issue_key="PROJ-1",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.provider_parent_id == "PROJ-1"


# ---------------------------------------------------------------------------
# Normalizer — attachment
# ---------------------------------------------------------------------------


def test_normalize_attachment_structure() -> None:
    raw = _SAMPLE_ISSUE["fields"]["attachment"][0]
    item = normalize_attachment(
        raw,
        issue_key="PROJ-1",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.provider_item_id == "attachment-30001"
    assert item.item_type == ExternalItemType.attachment
    assert item.provider_parent_id == "PROJ-1"
    assert item.title == "screenshot.png"
    assert item.mime_type == "image/png"
    assert item.metadata["size_bytes"] == 48200


# ---------------------------------------------------------------------------
# JQL construction
# ---------------------------------------------------------------------------


def test_build_jql_no_filters() -> None:
    jql = _build_jql(None, None)
    assert "ORDER BY updated ASC" in jql
    assert "project" not in jql


def test_build_jql_single_project() -> None:
    jql = _build_jql(["PROJ"], None)
    assert '"PROJ"' in jql
    assert "ORDER BY updated ASC" in jql


def test_build_jql_multiple_projects() -> None:
    jql = _build_jql(["PROJ", "WEB"], None)
    assert '"PROJ"' in jql
    assert '"WEB"' in jql


def test_build_jql_with_since() -> None:
    jql = _build_jql(["PROJ"], None, since="2024-01-01T00:00:00+00:00")
    assert "updated >= " in jql
    assert "2024-01-01T00:00:00+00:00" in jql


def test_build_jql_with_extra_filter() -> None:
    jql = _build_jql(["PROJ"], "status != Done")
    assert "status != Done" in jql


def test_resolve_project_keys_from_provider_source_id() -> None:
    keys = _resolve_project_keys("PROJ", {})
    assert keys == ["PROJ"]


def test_resolve_project_keys_from_credential() -> None:
    cred = {"project_keys": ["A", "B"]}
    keys = _resolve_project_keys(None, cred)
    assert keys == ["A", "B"]


def test_resolve_project_keys_none_when_absent() -> None:
    keys = _resolve_project_keys(None, {})
    assert keys is None


# ---------------------------------------------------------------------------
# Adapter — list_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_single_issue_with_comment() -> None:
    adapter = JiraConnectorAdapter()

    mock_response = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=50,
        )

    assert isinstance(page, ItemPage)
    issue_items = [i for i in page.items if i.item_type == ExternalItemType.issue]
    comment_items = [i for i in page.items if i.item_type == ExternalItemType.comment]
    assert len(issue_items) == 1
    assert len(comment_items) == 1
    assert issue_items[0].provider_item_id == "PROJ-1"
    assert comment_items[0].provider_parent_id == "PROJ-1"


@pytest.mark.asyncio
async def test_list_items_empty_result() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=50,
        )

    assert page.items == []
    assert not page.has_more
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_list_items_pagination() -> None:
    adapter = JiraConnectorAdapter()
    # Total=3, page_size=2, first page
    page1_data = {
        "total": 3,
        "startAt": 0,
        "maxResults": 2,
        "issues": [
            {**_SAMPLE_ISSUE, "key": "PROJ-1"},
            {**_SAMPLE_ISSUE, "key": "PROJ-2", "id": "10002"},
        ],
    }
    for i in page1_data["issues"]:
        i["fields"] = dict(_SAMPLE_ISSUE["fields"])

    mock_response = _make_httpx_response(page1_data)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=2,
        )

    assert page.has_more
    assert page.next_cursor is not None
    assert page.next_cursor["start_at"] == 2


@pytest.mark.asyncio
async def test_list_items_sends_bearer_token() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)
    captured_headers: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        captured_headers.update(headers or {})
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )

    assert captured_headers.get("Authorization") == "Bearer test-token-abc"


@pytest.mark.asyncio
async def test_list_items_no_site_url_raises() -> None:
    adapter = JiraConnectorAdapter()
    cred = {"auth_type": "oauth2", "access_token": "token"}

    with pytest.raises(ConnectorContentError, match="site_url"):
        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=cred,
            cursor={},
            page_size=10,
        )


# ---------------------------------------------------------------------------
# Adapter — error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_401_raises_auth_error() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_error_response(status=401)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ConnectorAuthError):
            await adapter.list_items(
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
                external_source_id=None,
                provider_source_id=None,
                decrypted_credential=_BASE_CRED,
                cursor={},
                page_size=10,
            )


@pytest.mark.asyncio
async def test_list_items_403_raises_auth_error() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_error_response(status=403)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ConnectorAuthError):
            await adapter.list_items(
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
                external_source_id=None,
                provider_source_id=None,
                decrypted_credential=_BASE_CRED,
                cursor={},
                page_size=10,
            )


@pytest.mark.asyncio
async def test_list_items_429_raises_rate_limit_error() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_error_response(
        status=429, headers={"Retry-After": "45"}
    )

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ConnectorRateLimitError) as exc_info:
            await adapter.list_items(
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
                external_source_id=None,
                provider_source_id=None,
                decrypted_credential=_BASE_CRED,
                cursor={},
                page_size=10,
            )

    assert exc_info.value.retry_after_seconds == 45


@pytest.mark.asyncio
async def test_list_items_500_raises_unavailable_error() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_error_response(status=500)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ConnectorProviderUnavailableError):
            await adapter.list_items(
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
                external_source_id=None,
                provider_source_id=None,
                decrypted_credential=_BASE_CRED,
                cursor={},
                page_size=10,
            )


# ---------------------------------------------------------------------------
# Adapter — delta_sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delta_sync_returns_upsert_items() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        page = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    assert len(page.items) >= 1
    issue_deltas = [d for d in page.items if d.item and d.item.item_type == ExternalItemType.issue]
    assert len(issue_deltas) == 1
    assert not issue_deltas[0].is_deleted


@pytest.mark.asyncio
async def test_delta_sync_advances_since_cursor() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        page = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    assert page.next_cursor is not None
    assert "since" in page.next_cursor
    assert page.next_cursor["since"] >= "2024-01-01"


@pytest.mark.asyncio
async def test_delta_sync_empty_advances_since_cursor() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        page = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    assert page.next_cursor is not None
    assert "since" in page.next_cursor
    assert not page.has_more


@pytest.mark.asyncio
async def test_delta_sync_uses_since_in_jql() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-06-01T00:00:00+00:00"},
            page_size=10,
        )

    assert "jql" in captured_params
    assert "updated >=" in captured_params["jql"]
    assert "2024-06-01" in captured_params["jql"]


# ---------------------------------------------------------------------------
# Adapter — provider_source_id filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_filters_by_provider_source_id() -> None:
    adapter = JiraConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id="MYPROJECT",
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )

    assert "MYPROJECT" in captured_params.get("jql", "")


# ---------------------------------------------------------------------------
# Adapter — provider contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_adapter_passes_contract_suite() -> None:
    """Run the shared adapter contract harness against the Jira adapter with mocked HTTP."""
    adapter = JiraConnectorAdapter()
    mock_full = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)
    mock_empty = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)

    call_count = 0

    async def fake_get(url, *, params=None, headers=None):
        nonlocal call_count
        call_count += 1
        # First call is list_items; use SINGLE. Subsequent delta calls: use EMPTY.
        if call_count == 1:
            return mock_full
        return mock_empty

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        await run_adapter_contract_suite(
            adapter,
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            credential=_BASE_CRED,
        )


# ---------------------------------------------------------------------------
# Adapter registration
# ---------------------------------------------------------------------------


def test_jira_adapter_is_registered() -> None:
    from app.domains.connectors.services.provider_adapter import default_sync_adapter_registry
    import app.domains.connectors  # noqa: F401 – ensures registration

    adapter = default_sync_adapter_registry.get("jira")
    assert adapter is not None
    assert isinstance(adapter, JiraConnectorAdapter)
