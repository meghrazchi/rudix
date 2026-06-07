"""Tests for F243: Confluence connector adapter.

Covers:
- HTML storage-format to plain text extraction
- Page normalization (fields, metadata, breadcrumb, URL)
- Comment normalization (structure, parent ID requirement)
- Attachment normalization (structure, mime type, download URL)
- CQL construction (space filter, since, cql_filter)
- Space key resolution (provider_source_id > credential.space_keys > None)
- list_items() full sync pagination
- delta_sync() incremental sync with since cursor
- fetch_attachments() per-page
- Error mapping: 401 → ConnectorAuthError, 429 → ConnectorRateLimitError, 5xx → unavailable
- Missing site_url raises ConnectorContentError
- include_comments flag triggers comment fetch
- Provider contract suite
- Adapter registration
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from app.domains.connectors.providers.confluence.adapter import (
    ConfluenceConnectorAdapter,
    _build_cql,
    _resolve_space_keys,
)
from app.domains.connectors.providers.confluence.normalizer import (
    _page_content_hash,
    _storage_html_to_text,
    normalize_attachment,
    normalize_comment,
    normalize_page,
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

pytestmark = pytest.mark.confluence_adapter

_ORG_ID = str(uuid4())
_CONN_ID = str(uuid4())
_ORG_UUID = UUID(_ORG_ID)
_CONN_UUID = UUID(_CONN_ID)

_BASE_CRED = {
    "auth_type": "oauth2",
    "access_token": "test-token-abc",
    "site_url": "https://mysite.atlassian.net",
}

_SAMPLE_PAGE = {
    "id": "123456",
    "type": "page",
    "status": "current",
    "title": "Getting Started Guide",
    "space": {"key": "DOCS", "name": "Documentation"},
    "version": {
        "number": 3,
        "when": "2024-06-01T10:00:00.000Z",
        "by": {"accountId": "acc-1", "displayName": "Alice Smith"},
    },
    "ancestors": [
        {"id": "111111", "type": "page", "title": "Home"},
        {"id": "222222", "type": "page", "title": "Onboarding"},
    ],
    "body": {
        "storage": {
            "value": "<p>Welcome to the platform. <strong>Read carefully.</strong></p>",
            "representation": "storage",
        }
    },
    "metadata": {
        "labels": {
            "results": [
                {"name": "docs", "prefix": "global"},
                {"name": "onboarding", "prefix": "global"},
            ]
        }
    },
    "history": {
        "createdDate": "2024-01-01T08:00:00.000Z",
        "createdBy": {"accountId": "acc-2", "displayName": "Bob Jones"},
    },
    "_links": {
        "webui": "/spaces/DOCS/pages/123456/Getting+Started+Guide",
        "self": "https://mysite.atlassian.net/wiki/rest/api/content/123456",
    },
}

_SAMPLE_COMMENT = {
    "id": "789012",
    "type": "comment",
    "title": "Re: Getting Started Guide",
    "status": "current",
    "body": {
        "storage": {
            "value": "<p>This is very helpful, thank you!</p>",
        }
    },
    "version": {
        "number": 1,
        "when": "2024-03-01T09:00:00.000Z",
        "by": {"accountId": "acc-3", "displayName": "Carol"},
    },
}

_SAMPLE_ATTACHMENT = {
    "id": "att456",
    "type": "attachment",
    "title": "architecture-diagram.png",
    "extensions": {"mediaType": "image/png", "fileSize": 98765},
    "version": {
        "number": 1,
        "when": "2024-03-02T10:00:00.000Z",
        "by": {"accountId": "acc-1", "displayName": "Alice Smith"},
    },
    "_links": {
        "download": "/wiki/download/attachments/123456/architecture-diagram.png",
    },
}

_SEARCH_RESPONSE_SINGLE = {
    "results": [_SAMPLE_PAGE],
    "start": 0,
    "limit": 50,
    "size": 1,
    "_links": {},
}

_SEARCH_RESPONSE_EMPTY = {
    "results": [],
    "start": 0,
    "limit": 50,
    "size": 0,
    "_links": {},
}

_COMMENT_RESPONSE = {
    "results": [_SAMPLE_COMMENT],
    "start": 0,
    "limit": 25,
    "size": 1,
}

_ATTACHMENT_RESPONSE = {
    "results": [_SAMPLE_ATTACHMENT],
    "start": 0,
    "limit": 50,
    "size": 1,
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
        request=httpx.Request("GET", "https://mysite.atlassian.net/wiki/rest/api/content/search"),
    )


def _make_httpx_error_response(*, status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        content=b'{"message": "error"}',
        request=httpx.Request("GET", "https://mysite.atlassian.net/wiki/rest/api/content/search"),
    )


def _patch_client(responses: list[httpx.Response]):
    """Context manager that replaces httpx.AsyncClient.get with sequential mock responses."""
    call_count = 0

    async def fake_get(url, *, params=None, headers=None):
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = fake_get
    return mock_client


# ---------------------------------------------------------------------------
# HTML to text extraction
# ---------------------------------------------------------------------------


def test_storage_html_to_text_basic() -> None:
    result = _storage_html_to_text("<p>Hello world</p>")
    assert "Hello world" in result


def test_storage_html_to_text_nested_tags() -> None:
    result = _storage_html_to_text("<p>Welcome to the <strong>platform</strong>.</p>")
    assert "Welcome to the" in result
    assert "platform" in result


def test_storage_html_to_text_none() -> None:
    assert _storage_html_to_text(None) == ""


def test_storage_html_to_text_empty() -> None:
    assert _storage_html_to_text("") == ""


def test_storage_html_to_text_strips_all_tags() -> None:
    result = _storage_html_to_text("<h1>Title</h1><ul><li>Item 1</li><li>Item 2</li></ul>")
    assert "<" not in result
    assert "Title" in result
    assert "Item 1" in result


# ---------------------------------------------------------------------------
# Normalizer — page
# ---------------------------------------------------------------------------


def test_normalize_page_basic_fields() -> None:
    item = normalize_page(
        _SAMPLE_PAGE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.provider_key == "confluence"
    assert item.provider_item_id == "123456"
    assert item.item_type == ExternalItemType.wiki_page
    assert item.title == "Getting Started Guide"
    assert "mysite.atlassian.net" in item.source_url
    assert "/DOCS/" in item.source_url or "spaces" in item.source_url
    assert item.visibility == ExternalItemVisibility.org_wide
    assert len(item.content_hash) == 64


def test_normalize_page_metadata() -> None:
    item = normalize_page(
        _SAMPLE_PAGE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.metadata["space_key"] == "DOCS"
    assert item.metadata["space_name"] == "Documentation"
    assert item.metadata["version_number"] == 3
    assert item.metadata["last_editor_display_name"] == "Alice Smith"
    assert "docs" in item.metadata["labels"]
    assert "onboarding" in item.metadata["labels"]
    assert "Home" in item.metadata["breadcrumb"]
    assert "Onboarding" in item.metadata["breadcrumb"]


def test_normalize_page_parent_id() -> None:
    item = normalize_page(
        _SAMPLE_PAGE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.provider_parent_id == "222222"
    assert item.root_provider_item_id == "111111"


def test_normalize_page_no_ancestors() -> None:
    page = dict(_SAMPLE_PAGE)
    page["ancestors"] = []
    item = normalize_page(
        page,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.provider_parent_id is None
    assert item.root_provider_item_id is None


def test_normalize_page_content_hash_stability() -> None:
    h1 = _page_content_hash(_SAMPLE_PAGE)
    h2 = _page_content_hash(_SAMPLE_PAGE)
    assert h1 == h2
    assert len(h1) == 64


def test_normalize_page_url_uses_webui_link() -> None:
    item = normalize_page(
        _SAMPLE_PAGE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert (
        item.source_url
        == "https://mysite.atlassian.net/wiki/spaces/DOCS/pages/123456/Getting+Started+Guide"
    )


def test_normalize_page_url_fallback_without_webui() -> None:
    page = {**_SAMPLE_PAGE, "_links": {}}
    item = normalize_page(
        page,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert "123456" in item.source_url
    assert "DOCS" in item.source_url


# ---------------------------------------------------------------------------
# Normalizer — comment
# ---------------------------------------------------------------------------


def test_normalize_comment_structure() -> None:
    item = normalize_comment(
        _SAMPLE_COMMENT,
        page_id="123456",
        page_url="https://mysite.atlassian.net/wiki/spaces/DOCS/pages/123456",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.provider_item_id == "comment-789012"
    assert item.item_type == ExternalItemType.comment
    assert item.provider_parent_id == "123456"
    assert item.root_provider_item_id == "123456"
    assert "Carol" in item.title
    assert "focusedCommentId=789012" in item.source_url
    assert item.metadata["author_display_name"] == "Carol"


def test_normalize_comment_title_includes_snippet() -> None:
    item = normalize_comment(
        _SAMPLE_COMMENT,
        page_id="123456",
        page_url="https://mysite.atlassian.net/wiki/spaces/DOCS/pages/123456",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert "helpful" in item.title


def test_normalize_comment_has_parent_id() -> None:
    item = normalize_comment(
        _SAMPLE_COMMENT,
        page_id="123456",
        page_url="https://mysite.atlassian.net/wiki/spaces/DOCS/pages/123456",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.provider_parent_id is not None


# ---------------------------------------------------------------------------
# Normalizer — attachment
# ---------------------------------------------------------------------------


def test_normalize_attachment_structure() -> None:
    item = normalize_attachment(
        _SAMPLE_ATTACHMENT,
        page_id="123456",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert item.provider_item_id == "attachment-att456"
    assert item.item_type == ExternalItemType.attachment
    assert item.provider_parent_id == "123456"
    assert item.root_provider_item_id == "123456"
    assert item.title == "architecture-diagram.png"
    assert item.mime_type == "image/png"
    assert item.metadata["size_bytes"] == 98765
    assert item.metadata["author_display_name"] == "Alice Smith"


def test_normalize_attachment_download_url() -> None:
    item = normalize_attachment(
        _SAMPLE_ATTACHMENT,
        page_id="123456",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert (
        item.source_url
        == "https://mysite.atlassian.net/wiki/download/attachments/123456/architecture-diagram.png"
    )


def test_normalize_attachment_download_url_fallback() -> None:
    att = {**_SAMPLE_ATTACHMENT, "_links": {}}
    item = normalize_attachment(
        att,
        page_id="123456",
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        site_url="https://mysite.atlassian.net",
        sync_version=1,
    )
    assert "123456" in item.source_url


# ---------------------------------------------------------------------------
# CQL construction
# ---------------------------------------------------------------------------


def test_build_cql_no_filters() -> None:
    cql = _build_cql(None, None)
    assert 'type = "page"' in cql
    assert "ORDER BY lastModified ASC" in cql
    assert "space.key" not in cql


def test_build_cql_single_space() -> None:
    cql = _build_cql(["DOCS"], None)
    assert '"DOCS"' in cql
    assert "space.key in" in cql


def test_build_cql_multiple_spaces() -> None:
    cql = _build_cql(["DOCS", "ENG"], None)
    assert '"DOCS"' in cql
    assert '"ENG"' in cql


def test_build_cql_with_since() -> None:
    cql = _build_cql(["DOCS"], None, since="2024-01-01T00:00:00+00:00")
    assert "lastModified >= " in cql
    assert "2024-01-01T00:00:00+00:00" in cql


def test_build_cql_with_extra_filter() -> None:
    cql = _build_cql(["DOCS"], 'label = "docs"')
    assert 'label = "docs"' in cql


def test_resolve_space_keys_from_provider_source_id() -> None:
    keys = _resolve_space_keys("MYSPACE", {})
    assert keys == ["MYSPACE"]


def test_resolve_space_keys_from_credential() -> None:
    cred = {"space_keys": ["A", "B"]}
    keys = _resolve_space_keys(None, cred)
    assert keys == ["A", "B"]


def test_resolve_space_keys_none_when_absent() -> None:
    keys = _resolve_space_keys(None, {})
    assert keys is None


# ---------------------------------------------------------------------------
# Adapter — list_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_single_page() -> None:
    adapter = ConfluenceConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patch_client([mock_response])

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
    wiki_items = [i for i in page.items if i.item_type == ExternalItemType.wiki_page]
    assert len(wiki_items) == 1
    assert wiki_items[0].provider_item_id == "123456"
    assert wiki_items[0].title == "Getting Started Guide"


@pytest.mark.asyncio
async def test_list_items_empty_result() -> None:
    adapter = ConfluenceConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patch_client([mock_response])

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
async def test_list_items_pagination_has_more() -> None:
    adapter = ConfluenceConnectorAdapter()
    page1_data = {
        "results": [_SAMPLE_PAGE, {**_SAMPLE_PAGE, "id": "654321", "title": "Page 2"}],
        "start": 0,
        "limit": 2,
        "size": 2,
        "_links": {"next": "/wiki/rest/api/content/search?cql=...&start=2"},
    }
    mock_response = _make_httpx_response(page1_data)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patch_client([mock_response])

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
    assert page.next_cursor["start"] == 2


@pytest.mark.asyncio
async def test_list_items_sends_bearer_token() -> None:
    adapter = ConfluenceConnectorAdapter()
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
    adapter = ConfluenceConnectorAdapter()
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


@pytest.mark.asyncio
async def test_list_items_with_comments_fetches_comment_endpoint() -> None:
    adapter = ConfluenceConnectorAdapter()
    search_resp = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)
    comment_resp = _make_httpx_response(_COMMENT_RESPONSE)

    urls_called: list[str] = []

    async def fake_get(url, *, params=None, headers=None):
        urls_called.append(url)
        if "comment" in url:
            return comment_resp
        return search_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_client_cls.return_value = mock_client

        cred = {**_BASE_CRED, "include_comments": True}
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=cred,
            cursor={},
            page_size=50,
        )

    comment_items = [i for i in page.items if i.item_type == ExternalItemType.comment]
    assert len(comment_items) == 1
    assert comment_items[0].provider_parent_id == "123456"
    assert any("comment" in u for u in urls_called)


@pytest.mark.asyncio
async def test_list_items_no_comments_by_default() -> None:
    adapter = ConfluenceConnectorAdapter()
    search_resp = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)
    urls_called: list[str] = []

    async def fake_get(url, *, params=None, headers=None):
        urls_called.append(url)
        return search_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
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

    comment_items = [i for i in page.items if i.item_type == ExternalItemType.comment]
    assert len(comment_items) == 0
    assert not any("comment" in u for u in urls_called)


# ---------------------------------------------------------------------------
# Adapter — error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_401_raises_auth_error() -> None:
    adapter = ConfluenceConnectorAdapter()
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
    adapter = ConfluenceConnectorAdapter()
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
    adapter = ConfluenceConnectorAdapter()
    mock_response = _make_httpx_error_response(status=429, headers={"Retry-After": "30"})

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

    assert exc_info.value.retry_after_seconds == 30


@pytest.mark.asyncio
async def test_list_items_500_raises_unavailable_error() -> None:
    adapter = ConfluenceConnectorAdapter()
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
    adapter = ConfluenceConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patch_client([mock_response])

        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    page_deltas = [
        d for d in delta.items if d.item and d.item.item_type == ExternalItemType.wiki_page
    ]
    assert len(page_deltas) == 1
    assert not page_deltas[0].is_deleted


@pytest.mark.asyncio
async def test_delta_sync_advances_since_cursor() -> None:
    adapter = ConfluenceConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patch_client([mock_response])

        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    assert delta.next_cursor is not None
    assert "since" in delta.next_cursor
    assert delta.next_cursor["since"] >= "2024-01-01"


@pytest.mark.asyncio
async def test_delta_sync_uses_since_in_cql() -> None:
    adapter = ConfluenceConnectorAdapter()
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

    assert "cql" in captured_params
    assert "lastModified >=" in captured_params["cql"]
    assert "2024-06-01" in captured_params["cql"]


@pytest.mark.asyncio
async def test_delta_sync_empty_preserves_since_cursor() -> None:
    adapter = ConfluenceConnectorAdapter()
    mock_response = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _patch_client([mock_response])

        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    assert delta.next_cursor is not None
    assert "since" in delta.next_cursor
    assert not delta.has_more


# ---------------------------------------------------------------------------
# Adapter — fetch_attachments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_attachments_returns_items() -> None:
    adapter = ConfluenceConnectorAdapter()
    mock_response = _make_httpx_response(_ATTACHMENT_RESPONSE)

    cred = {
        **_BASE_CRED,
        "_organization_id": _ORG_ID,
        "_connection_id": _CONN_ID,
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        items = await adapter.fetch_attachments(
            provider_item_id="123456",
            decrypted_credential=cred,
        )

    assert len(items) == 1
    assert items[0].item_type == ExternalItemType.attachment
    assert items[0].provider_parent_id == "123456"
    assert items[0].title == "architecture-diagram.png"


@pytest.mark.asyncio
async def test_fetch_attachments_missing_org_id_returns_empty() -> None:
    adapter = ConfluenceConnectorAdapter()

    items = await adapter.fetch_attachments(
        provider_item_id="123456",
        decrypted_credential=_BASE_CRED,
    )

    assert items == []


# ---------------------------------------------------------------------------
# Adapter — provider_source_id filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_filters_by_provider_source_id() -> None:
    adapter = ConfluenceConnectorAdapter()
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
            provider_source_id="MYSPACE",
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )

    assert "MYSPACE" in captured_params.get("cql", "")


# ---------------------------------------------------------------------------
# Adapter — provider contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confluence_adapter_passes_contract_suite() -> None:
    """Run the shared adapter contract harness against the Confluence adapter."""
    adapter = ConfluenceConnectorAdapter()
    mock_full = _make_httpx_response(_SEARCH_RESPONSE_SINGLE)
    mock_empty = _make_httpx_response(_SEARCH_RESPONSE_EMPTY)

    call_count = 0

    async def fake_get(url, *, params=None, headers=None):
        nonlocal call_count
        call_count += 1
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


def test_confluence_adapter_is_registered() -> None:
    from app.domains.connectors.services.provider_adapter import default_sync_adapter_registry
    import app.domains.connectors  # noqa: F401 – ensures registration

    adapter = default_sync_adapter_registry.get("confluence")
    assert adapter is not None
    assert isinstance(adapter, ConfluenceConnectorAdapter)
