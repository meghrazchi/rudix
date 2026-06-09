"""Tests for F274: Notion connector adapter.

Covers:
- Rich-text to plain text extraction
- Page title extraction from properties
- Page normalization (fields, metadata, provider_item_id, content_hash)
- Database normalization (folder type, title, parent)
- Comment normalization (parent_id requirement, title truncation)
- File block normalization (attachment type, mime type, URL)
- Block content renderer (headings, paragraphs, lists, code, tables, toggles, nested)
- list_items() full sync: search endpoint pagination, archived page filtering
- list_items() scoped to page_ids / database_ids with cursor
- delta_sync(): archived pages emitted as is_deleted=True DeltaItems
- delta_sync(): cursor advances since timestamp after last page
- fetch_attachments(): returns empty list when include_attachments=False
- fetch_attachments(): returns file blocks for pages with attachments
- download_file_content(): renders page blocks to text/plain
- download_file_content(): downloads hosted file for block: prefix
- Error mapping: 401 → ConnectorAuthError, 429 → ConnectorRateLimitError, 5xx → unavailable
- Missing access_token raises ConnectorAuthError
- Provider registration in registry
- Adapter registration in default_sync_adapter_registry
- Contract suite passes
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.domains.connectors.providers.notion.adapter import NotionConnectorAdapter
from app.domains.connectors.providers.notion.normalizer import (
    NOTION_FILE_BLOCK_TYPES,
    extract_database_title,
    extract_page_title,
    extract_parent_id,
    normalize_comment,
    normalize_database,
    normalize_file_block,
    normalize_page,
    render_blocks_to_text,
)
from app.domains.connectors.sdk.testing import run_adapter_contract_suite
from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorProviderUnavailableError,
    ConnectorRateLimitError,
)
from app.models.enums import ExternalItemType, ExternalItemVisibility

pytestmark = pytest.mark.notion_adapter

_ORG_ID = str(uuid4())
_CONN_ID = str(uuid4())
_ORG_UUID = UUID(_ORG_ID)
_CONN_UUID = UUID(_CONN_ID)
_WORKSPACE_ID = "ws-abc123"

_BASE_CRED = {
    "auth_type": "oauth2",
    "access_token": "secret-token",
    "workspace_id": _WORKSPACE_ID,
}

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_SAMPLE_PAGE_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
_SAMPLE_DB_ID = "db11db11-db11-db11-db11-db11db11db11"

_SAMPLE_PAGE: dict[str, Any] = {
    "object": "page",
    "id": _SAMPLE_PAGE_ID,
    "url": f"https://www.notion.so/{_SAMPLE_PAGE_ID.replace('-', '')}",
    "created_time": "2024-01-01T10:00:00.000Z",
    "last_edited_time": "2024-06-01T12:00:00.000Z",
    "archived": False,
    "parent": {"type": "workspace", "workspace": True},
    "created_by": {"id": "user-1"},
    "last_edited_by": {"id": "user-2"},
    "properties": {
        "title": {
            "type": "title",
            "title": [{"plain_text": "Getting Started", "type": "text"}],
        }
    },
}

_SAMPLE_DB_PAGE: dict[str, Any] = {
    "object": "page",
    "id": "page-in-db-0001",
    "url": "https://www.notion.so/pageindb0001",
    "created_time": "2024-02-01T10:00:00.000Z",
    "last_edited_time": "2024-06-02T12:00:00.000Z",
    "archived": False,
    "parent": {"type": "database_id", "database_id": _SAMPLE_DB_ID},
    "created_by": {"id": "user-1"},
    "last_edited_by": {"id": "user-1"},
    "properties": {
        "Name": {
            "type": "title",
            "title": [{"plain_text": "Task Alpha", "type": "text"}],
        }
    },
}

_SAMPLE_DATABASE: dict[str, Any] = {
    "object": "database",
    "id": _SAMPLE_DB_ID,
    "url": f"https://www.notion.so/{_SAMPLE_DB_ID.replace('-', '')}",
    "created_time": "2024-01-15T08:00:00.000Z",
    "last_edited_time": "2024-05-20T09:00:00.000Z",
    "archived": False,
    "parent": {"type": "workspace", "workspace": True},
    "title": [{"plain_text": "Project Tracker", "type": "text"}],
    "properties": {},
}

_SAMPLE_COMMENT: dict[str, Any] = {
    "object": "comment",
    "id": "comment-0001",
    "created_time": "2024-04-01T08:00:00.000Z",
    "last_edited_time": "2024-04-01T08:05:00.000Z",
    "created_by": {"id": "user-3"},
    "rich_text": [{"plain_text": "Great page!", "type": "text"}],
}

_SAMPLE_FILE_BLOCK: dict[str, Any] = {
    "object": "block",
    "id": "block-file-0001",
    "type": "pdf",
    "last_edited_time": "2024-03-01T10:00:00.000Z",
    "has_children": False,
    "pdf": {
        "caption": [{"plain_text": "Architecture diagram", "type": "text"}],
        "file": {
            "url": "https://prod-files-secure.s3.amazonaws.com/sample.pdf?X-Amz-Expires=3600",
        },
    },
}

_SAMPLE_BLOCKS: list[dict[str, Any]] = [
    {
        "object": "block",
        "id": "blk-h1",
        "type": "heading_1",
        "has_children": False,
        "heading_1": {"rich_text": [{"plain_text": "Introduction", "type": "text"}]},
    },
    {
        "object": "block",
        "id": "blk-p1",
        "type": "paragraph",
        "has_children": False,
        "paragraph": {"rich_text": [{"plain_text": "Welcome to Rudix.", "type": "text"}]},
    },
    {
        "object": "block",
        "id": "blk-ul",
        "type": "bulleted_list_item",
        "has_children": False,
        "bulleted_list_item": {"rich_text": [{"plain_text": "Item one", "type": "text"}]},
    },
    {
        "object": "block",
        "id": "blk-code",
        "type": "code",
        "has_children": False,
        "code": {
            "language": "python",
            "rich_text": [{"plain_text": "print('hello')", "type": "text"}],
        },
    },
]

_SEARCH_RESPONSE_SINGLE: dict[str, Any] = {
    "object": "list",
    "results": [_SAMPLE_PAGE],
    "has_more": False,
    "next_cursor": None,
}

_SEARCH_RESPONSE_WITH_DB: dict[str, Any] = {
    "object": "list",
    "results": [_SAMPLE_PAGE, _SAMPLE_DATABASE],
    "has_more": False,
    "next_cursor": None,
}

_SEARCH_RESPONSE_PAGE_1: dict[str, Any] = {
    "object": "list",
    "results": [_SAMPLE_PAGE],
    "has_more": True,
    "next_cursor": "cursor-abc",
}

_SEARCH_RESPONSE_PAGE_2: dict[str, Any] = {
    "object": "list",
    "results": [_SAMPLE_DB_PAGE],
    "has_more": False,
    "next_cursor": None,
}

_BLOCKS_RESPONSE: dict[str, Any] = {
    "object": "list",
    "results": _SAMPLE_BLOCKS,
    "has_more": False,
    "next_cursor": None,
}


# ---------------------------------------------------------------------------
# HTTP mock helpers
# ---------------------------------------------------------------------------


def _json_response(data: dict[str, Any], *, url: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers={"content-type": "application/json"},
        content=json.dumps(data).encode(),
        request=httpx.Request("POST", url),
    )


class _FakeNotionClient:
    """Fake httpx.AsyncClient that replays a response queue for Notion API calls."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeNotionClient:
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append({"method": "POST", "url": url, "json": json})
        if not self.responses:
            raise AssertionError(f"Unexpected POST: {url}")
        return self.responses.pop(0)

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        self.calls.append({"method": "GET", "url": url, "params": params or {}})
        if not self.responses:
            raise AssertionError(f"Unexpected GET: {url}")
        return self.responses.pop(0)


def _patch_notion_client(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[httpx.Response],
) -> _FakeNotionClient:
    client = _FakeNotionClient(responses)

    def _factory(*_: object, **__: object) -> _FakeNotionClient:
        return client

    import app.domains.connectors.providers.notion.adapter as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _factory)
    return client


# ---------------------------------------------------------------------------
# Normalizer unit tests
# ---------------------------------------------------------------------------


class TestExtractPageTitle:
    def test_extracts_title_from_title_property(self) -> None:
        assert extract_page_title(_SAMPLE_PAGE) == "Getting Started"

    def test_extracts_title_from_non_title_key(self) -> None:
        page = {
            "id": "x",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "Task Alpha"}],
                }
            },
        }
        assert extract_page_title(page) == "Task Alpha"

    def test_falls_back_to_id_when_no_title(self) -> None:
        page = {"id": "fallback-id", "properties": {}}
        assert extract_page_title(page) == "fallback-id"

    def test_empty_rich_text_falls_back_to_id(self) -> None:
        page = {
            "id": "fallback-id",
            "properties": {"title": {"type": "title", "title": []}},
        }
        assert extract_page_title(page) == "fallback-id"


class TestExtractDatabaseTitle:
    def test_extracts_title(self) -> None:
        assert extract_database_title(_SAMPLE_DATABASE) == "Project Tracker"

    def test_falls_back_to_id(self) -> None:
        db = {"id": "db-fallback", "title": []}
        assert extract_database_title(db) == "db-fallback"


class TestExtractParentId:
    def test_page_parent(self) -> None:
        parent = {"type": "page_id", "page_id": "parent-page-uuid"}
        assert extract_parent_id(parent) == "parent-page-uuid"

    def test_database_parent(self) -> None:
        parent = {"type": "database_id", "database_id": "db-uuid"}
        assert extract_parent_id(parent) == "db-uuid"

    def test_workspace_parent_returns_none(self) -> None:
        parent = {"type": "workspace", "workspace": True}
        assert extract_parent_id(parent) is None

    def test_none_parent_returns_none(self) -> None:
        assert extract_parent_id(None) is None


class TestNormalizePage:
    def _normalize(self, page: dict[str, Any] | None = None) -> Any:
        return normalize_page(
            page or _SAMPLE_PAGE,
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            workspace_id=_WORKSPACE_ID,
            sync_version=1,
        )

    def test_item_type_is_cloud_file(self) -> None:
        item = self._normalize()
        assert item.item_type == ExternalItemType.cloud_file

    def test_mime_type_is_text_plain(self) -> None:
        item = self._normalize()
        assert item.mime_type == "text/plain"

    def test_title_extracted_from_properties(self) -> None:
        item = self._normalize()
        assert item.title == "Getting Started"

    def test_provider_key_is_notion(self) -> None:
        assert self._normalize().provider_key == "notion"

    def test_provider_item_id_is_page_id(self) -> None:
        assert self._normalize().provider_item_id == _SAMPLE_PAGE_ID

    def test_source_url_from_page(self) -> None:
        item = self._normalize()
        assert item.source_url == _SAMPLE_PAGE["url"]

    def test_root_provider_item_id_is_workspace(self) -> None:
        assert self._normalize().root_provider_item_id == _WORKSPACE_ID

    def test_parent_id_none_for_workspace_root(self) -> None:
        assert self._normalize().provider_parent_id is None

    def test_parent_id_set_for_db_item(self) -> None:
        item = normalize_page(
            _SAMPLE_DB_PAGE,
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            workspace_id=_WORKSPACE_ID,
            sync_version=1,
        )
        assert item.provider_parent_id == _SAMPLE_DB_ID

    def test_metadata_includes_page_id(self) -> None:
        assert self._normalize().metadata["page_id"] == _SAMPLE_PAGE_ID

    def test_metadata_in_database_for_db_item(self) -> None:
        item = normalize_page(
            _SAMPLE_DB_PAGE,
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            workspace_id=_WORKSPACE_ID,
            sync_version=1,
        )
        assert item.metadata.get("in_database") is True
        assert item.metadata.get("database_id") == _SAMPLE_DB_ID

    def test_archived_in_metadata_when_set(self) -> None:
        archived_page = {**_SAMPLE_PAGE, "archived": True}
        item = normalize_page(
            archived_page,
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            workspace_id=_WORKSPACE_ID,
            sync_version=1,
        )
        assert item.metadata.get("archived") is True

    def test_content_hash_changes_on_edit(self) -> None:
        v1 = self._normalize()
        edited = {**_SAMPLE_PAGE, "last_edited_time": "2025-01-01T00:00:00.000Z"}
        v2 = normalize_page(
            edited,
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            workspace_id=_WORKSPACE_ID,
            sync_version=1,
        )
        assert v1.content_hash != v2.content_hash

    def test_visibility_is_org_wide(self) -> None:
        assert self._normalize().visibility == ExternalItemVisibility.org_wide

    def test_source_url_fallback_when_missing(self) -> None:
        page = {**_SAMPLE_PAGE, "url": ""}
        item = normalize_page(
            page,
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            workspace_id=_WORKSPACE_ID,
            sync_version=1,
        )
        assert item.source_url.startswith("https://www.notion.so/")


class TestNormalizeDatabase:
    def _normalize(self) -> Any:
        return normalize_database(
            _SAMPLE_DATABASE,
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            workspace_id=_WORKSPACE_ID,
            sync_version=1,
        )

    def test_item_type_is_folder(self) -> None:
        assert self._normalize().item_type == ExternalItemType.folder

    def test_title_from_title_array(self) -> None:
        assert self._normalize().title == "Project Tracker"

    def test_provider_item_id_is_database_id(self) -> None:
        assert self._normalize().provider_item_id == _SAMPLE_DB_ID

    def test_metadata_includes_database_id(self) -> None:
        assert self._normalize().metadata["database_id"] == _SAMPLE_DB_ID

    def test_root_is_workspace(self) -> None:
        assert self._normalize().root_provider_item_id == _WORKSPACE_ID


class TestNormalizeComment:
    def _normalize(self) -> Any:
        return normalize_comment(
            _SAMPLE_COMMENT,
            page_id=_SAMPLE_PAGE_ID,
            page_url=_SAMPLE_PAGE["url"],
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            sync_version=1,
        )

    def test_item_type_is_comment(self) -> None:
        assert self._normalize().item_type == ExternalItemType.comment

    def test_provider_item_id_has_comment_prefix(self) -> None:
        assert self._normalize().provider_item_id == "comment:comment-0001"

    def test_parent_id_is_page_id(self) -> None:
        assert self._normalize().provider_parent_id == _SAMPLE_PAGE_ID

    def test_title_contains_body_snippet(self) -> None:
        assert "Great page!" in self._normalize().title

    def test_source_url_is_page_url(self) -> None:
        assert self._normalize().source_url == _SAMPLE_PAGE["url"]

    def test_long_body_is_truncated_in_title(self) -> None:
        long_comment = {
            **_SAMPLE_COMMENT,
            "id": "c2",
            "rich_text": [{"plain_text": "X" * 200, "type": "text"}],
        }
        item = normalize_comment(
            long_comment,
            page_id=_SAMPLE_PAGE_ID,
            page_url=_SAMPLE_PAGE["url"],
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            sync_version=1,
        )
        assert len(item.title) <= 512
        assert "…" in item.title


class TestNormalizeFileBlock:
    def _normalize(self) -> Any:
        return normalize_file_block(
            _SAMPLE_FILE_BLOCK,
            page_id=_SAMPLE_PAGE_ID,
            page_url=_SAMPLE_PAGE["url"],
            organization_id=_ORG_UUID,
            connection_id=_CONN_UUID,
            external_source_id=None,
            sync_version=1,
        )

    def test_item_type_is_attachment(self) -> None:
        assert self._normalize().item_type == ExternalItemType.attachment

    def test_provider_item_id_has_block_prefix(self) -> None:
        assert self._normalize().provider_item_id == "block:block-file-0001"

    def test_mime_type_pdf_for_pdf_block(self) -> None:
        assert self._normalize().mime_type == "application/pdf"

    def test_parent_id_is_page_id(self) -> None:
        assert self._normalize().provider_parent_id == _SAMPLE_PAGE_ID

    def test_title_from_caption(self) -> None:
        assert "Architecture diagram" in self._normalize().title

    def test_source_url_is_file_url(self) -> None:
        url = self._normalize().source_url
        assert "s3.amazonaws.com" in url


class TestRenderBlocksToText:
    def test_heading_1_rendered_with_hash(self) -> None:
        text = render_blocks_to_text(_SAMPLE_BLOCKS)
        assert "# Introduction" in text

    def test_paragraph_rendered(self) -> None:
        text = render_blocks_to_text(_SAMPLE_BLOCKS)
        assert "Welcome to Rudix." in text

    def test_bulleted_list_item_rendered(self) -> None:
        text = render_blocks_to_text(_SAMPLE_BLOCKS)
        assert "- Item one" in text

    def test_code_block_rendered_with_fences(self) -> None:
        text = render_blocks_to_text(_SAMPLE_BLOCKS)
        assert "```python" in text
        assert "print('hello')" in text

    def test_nested_blocks_rendered_with_indent(self) -> None:
        nested = [
            {
                "object": "block",
                "id": "parent-blk",
                "type": "toggle",
                "has_children": True,
                "toggle": {"rich_text": [{"plain_text": "Toggle title"}]},
                "_children": [
                    {
                        "object": "block",
                        "id": "child-blk",
                        "type": "paragraph",
                        "has_children": False,
                        "paragraph": {"rich_text": [{"plain_text": "Child content"}]},
                    }
                ],
            }
        ]
        text = render_blocks_to_text(nested)
        assert "Toggle title" in text
        assert "Child content" in text

    def test_table_row_rendered_as_pipe_separated(self) -> None:
        row_block = [
            {
                "object": "block",
                "id": "trow",
                "type": "table_row",
                "has_children": False,
                "table_row": {
                    "cells": [
                        [{"plain_text": "Col A"}],
                        [{"plain_text": "Col B"}],
                    ]
                },
            }
        ]
        text = render_blocks_to_text(row_block)
        assert "Col A" in text
        assert "Col B" in text
        assert "|" in text

    def test_empty_blocks_returns_empty_string(self) -> None:
        assert render_blocks_to_text([]) == ""

    def test_divider_rendered(self) -> None:
        divider = [
            {"object": "block", "id": "d", "type": "divider", "has_children": False, "divider": {}}
        ]
        assert "---" in render_blocks_to_text(divider)

    def test_unknown_block_type_skipped_silently(self) -> None:
        unknown = [
            {
                "object": "block",
                "id": "u",
                "type": "unsupported_widget",
                "has_children": False,
                "unsupported_widget": {},
            }
        ]
        text = render_blocks_to_text(unknown)
        assert text == ""


# ---------------------------------------------------------------------------
# Adapter integration tests
# ---------------------------------------------------------------------------


class TestListItemsFullScan:
    @pytest.mark.asyncio
    async def test_returns_page_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = _json_response(
            _SEARCH_RESPONSE_SINGLE,
            url="https://api.notion.com/v1/search",
        )
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )
        assert len(page.items) == 1
        assert page.items[0].provider_item_id == _SAMPLE_PAGE_ID
        assert page.has_more is False

    @pytest.mark.asyncio
    async def test_includes_databases_as_folder_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = _json_response(_SEARCH_RESPONSE_WITH_DB, url="https://api.notion.com/v1/search")
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )
        types = {i.item_type for i in page.items}
        assert ExternalItemType.cloud_file in types
        assert ExternalItemType.folder in types

    @pytest.mark.asyncio
    async def test_skips_archived_pages_in_full_scan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        archived_page = {**_SAMPLE_PAGE, "archived": True}
        resp = _json_response(
            {**_SEARCH_RESPONSE_SINGLE, "results": [archived_page]},
            url="https://api.notion.com/v1/search",
        )
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )
        assert len(page.items) == 0

    @pytest.mark.asyncio
    async def test_pagination_cursor_propagated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = _json_response(_SEARCH_RESPONSE_PAGE_1, url="https://api.notion.com/v1/search")
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=1,
        )
        assert page.has_more is True
        assert page.next_cursor == {"start_cursor": "cursor-abc"}

    @pytest.mark.asyncio
    async def test_include_comments_fetches_comments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        search_resp = _json_response(
            _SEARCH_RESPONSE_SINGLE, url="https://api.notion.com/v1/search"
        )
        comments_resp = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(
                {
                    "object": "list",
                    "results": [_SAMPLE_COMMENT],
                    "has_more": False,
                    "next_cursor": None,
                }
            ).encode(),
            request=httpx.Request(
                "GET", f"https://api.notion.com/v1/comments?block_id={_SAMPLE_PAGE_ID}"
            ),
        )
        _patch_notion_client(monkeypatch, [search_resp, comments_resp])
        cred = {**_BASE_CRED, "include_comments": True}
        adapter = NotionConnectorAdapter()
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=cred,
            cursor={},
            page_size=10,
        )
        comment_items = [i for i in page.items if i.item_type == ExternalItemType.comment]
        assert len(comment_items) == 1
        assert comment_items[0].provider_parent_id == _SAMPLE_PAGE_ID


class TestListItemsScoped:
    @pytest.mark.asyncio
    async def test_scoped_to_page_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page_resp = _json_response(_SAMPLE_PAGE, url=f"https://api.notion.com/v1/pages/{_SAMPLE_PAGE_ID}")
        page_resp = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(_SAMPLE_PAGE).encode(),
            request=httpx.Request("GET", f"https://api.notion.com/v1/pages/{_SAMPLE_PAGE_ID}"),
        )
        _patch_notion_client(monkeypatch, [page_resp])
        cred = {**_BASE_CRED, "page_ids": [_SAMPLE_PAGE_ID]}
        adapter = NotionConnectorAdapter()
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=cred,
            cursor={},
            page_size=10,
        )
        assert len(page.items) == 1
        assert page.items[0].provider_item_id == _SAMPLE_PAGE_ID

    @pytest.mark.asyncio
    async def test_scoped_skips_archived_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        archived = {**_SAMPLE_PAGE, "archived": True}
        page_resp = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(archived).encode(),
            request=httpx.Request("GET", f"https://api.notion.com/v1/pages/{_SAMPLE_PAGE_ID}"),
        )
        _patch_notion_client(monkeypatch, [page_resp])
        cred = {**_BASE_CRED, "page_ids": [_SAMPLE_PAGE_ID]}
        adapter = NotionConnectorAdapter()
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=cred,
            cursor={},
            page_size=10,
        )
        assert len(page.items) == 0

    @pytest.mark.asyncio
    async def test_scoped_404_page_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        not_found = httpx.Response(
            status_code=404,
            headers={"content-type": "application/json"},
            content=b'{"message": "not found"}',
            request=httpx.Request("GET", f"https://api.notion.com/v1/pages/{_SAMPLE_PAGE_ID}"),
        )
        _patch_notion_client(monkeypatch, [not_found])
        cred = {**_BASE_CRED, "page_ids": [_SAMPLE_PAGE_ID]}
        adapter = NotionConnectorAdapter()
        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=cred,
            cursor={},
            page_size=10,
        )
        assert len(page.items) == 0


class TestDeltaSync:
    @pytest.mark.asyncio
    async def test_live_page_emitted_as_not_deleted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = _json_response(_SEARCH_RESPONSE_SINGLE, url="https://api.notion.com/v1/search")
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=10,
        )
        assert len(delta.items) == 1
        assert delta.items[0].is_deleted is False
        assert delta.items[0].item is not None

    @pytest.mark.asyncio
    async def test_archived_page_emitted_as_deleted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        archived_page = {**_SAMPLE_PAGE, "archived": True}
        resp = _json_response(
            {**_SEARCH_RESPONSE_SINGLE, "results": [archived_page]},
            url="https://api.notion.com/v1/search",
        )
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )
        assert len(delta.items) == 1
        assert delta.items[0].is_deleted is True
        assert delta.items[0].item is None

    @pytest.mark.asyncio
    async def test_cursor_advances_since_after_last_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resp = _json_response(_SEARCH_RESPONSE_SINGLE, url="https://api.notion.com/v1/search")
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )
        assert delta.next_cursor is not None
        assert "since" in delta.next_cursor
        assert delta.next_cursor["start_cursor"] is None

    @pytest.mark.asyncio
    async def test_has_more_preserves_since_from_cursor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resp = _json_response(_SEARCH_RESPONSE_PAGE_1, url="https://api.notion.com/v1/search")
        _patch_notion_client(monkeypatch, [resp])
        original_since = "2024-01-01T00:00:00+00:00"
        adapter = NotionConnectorAdapter()
        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": original_since},
            page_size=1,
        )
        assert delta.has_more is True
        assert delta.next_cursor["since"] == original_since
        assert delta.next_cursor["start_cursor"] == "cursor-abc"


class TestFetchAttachments:
    @pytest.mark.asyncio
    async def test_returns_empty_when_attachments_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = NotionConnectorAdapter()
        result = await adapter.fetch_attachments(
            provider_item_id=_SAMPLE_PAGE_ID,
            decrypted_credential={**_BASE_CRED, "include_attachments": False},
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_without_org_conn_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = NotionConnectorAdapter()
        result = await adapter.fetch_attachments(
            provider_item_id=_SAMPLE_PAGE_ID,
            decrypted_credential={**_BASE_CRED, "include_attachments": True},
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_file_block_attachments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        blocks_resp = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(
                {
                    "object": "list",
                    "results": [_SAMPLE_FILE_BLOCK],
                    "has_more": False,
                    "next_cursor": None,
                }
            ).encode(),
            request=httpx.Request(
                "GET",
                f"https://api.notion.com/v1/blocks/{_SAMPLE_PAGE_ID}/children",
            ),
        )
        _patch_notion_client(monkeypatch, [blocks_resp])
        cred = {
            **_BASE_CRED,
            "include_attachments": True,
            "_organization_id": _ORG_ID,
            "_connection_id": _CONN_ID,
        }
        adapter = NotionConnectorAdapter()
        attachments = await adapter.fetch_attachments(
            provider_item_id=_SAMPLE_PAGE_ID,
            decrypted_credential=cred,
        )
        assert len(attachments) == 1
        assert attachments[0].item_type == ExternalItemType.attachment
        assert attachments[0].provider_item_id == "block:block-file-0001"


class TestDownloadFileContent:
    @pytest.mark.asyncio
    async def test_renders_page_blocks_to_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        blocks_resp = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(_BLOCKS_RESPONSE).encode(),
            request=httpx.Request(
                "GET",
                f"https://api.notion.com/v1/blocks/{_SAMPLE_PAGE_ID}/children",
            ),
        )
        _patch_notion_client(monkeypatch, [blocks_resp])
        adapter = NotionConnectorAdapter()
        result = await adapter.download_file_content(
            provider_item_id=_SAMPLE_PAGE_ID,
            mime_type="text/plain",
            decrypted_credential=_BASE_CRED,
        )
        assert result is not None
        content_bytes, filename, mime_type = result
        assert mime_type == "text/plain"
        assert filename.endswith(".txt")
        text = content_bytes.decode("utf-8")
        assert "Introduction" in text
        assert "Welcome to Rudix." in text

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        empty_resp = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(
                {"object": "list", "results": [], "has_more": False}
            ).encode(),
            request=httpx.Request(
                "GET",
                f"https://api.notion.com/v1/blocks/{_SAMPLE_PAGE_ID}/children",
            ),
        )
        _patch_notion_client(monkeypatch, [empty_resp])
        adapter = NotionConnectorAdapter()
        result = await adapter.download_file_content(
            provider_item_id=_SAMPLE_PAGE_ID,
            mime_type="text/plain",
            decrypted_credential=_BASE_CRED,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_downloads_block_file_by_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        block_resp = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            content=json.dumps(_SAMPLE_FILE_BLOCK).encode(),
            request=httpx.Request(
                "GET", "https://api.notion.com/v1/blocks/block-file-0001"
            ),
        )
        file_bytes = b"%PDF-1.4 fake content"
        file_resp = httpx.Response(
            status_code=200,
            content=file_bytes,
            request=httpx.Request(
                "GET",
                "https://prod-files-secure.s3.amazonaws.com/sample.pdf?X-Amz-Expires=3600",
            ),
        )
        _patch_notion_client(monkeypatch, [block_resp, file_resp])
        adapter = NotionConnectorAdapter()
        result = await adapter.download_file_content(
            provider_item_id="block:block-file-0001",
            mime_type=None,
            decrypted_credential=_BASE_CRED,
        )
        assert result is not None
        content, filename, mime_type = result
        assert mime_type == "application/pdf"
        assert content == file_bytes


class TestErrorMapping:
    @pytest.mark.asyncio
    async def test_missing_access_token_raises_auth_error(self) -> None:
        adapter = NotionConnectorAdapter()
        with pytest.raises(ConnectorAuthError):
            await adapter.list_items(
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
                external_source_id=None,
                provider_source_id=None,
                decrypted_credential={"auth_type": "oauth2"},
                cursor={},
                page_size=10,
            )

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = httpx.Response(
            status_code=401,
            headers={"content-type": "application/json"},
            content=b'{"message": "Unauthorized"}',
            request=httpx.Request("POST", "https://api.notion.com/v1/search"),
        )
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
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
    async def test_429_raises_rate_limit_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = httpx.Response(
            status_code=429,
            headers={"content-type": "application/json", "Retry-After": "30"},
            content=b'{"message": "Rate limited"}',
            request=httpx.Request("POST", "https://api.notion.com/v1/search"),
        )
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter()
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
    async def test_500_raises_provider_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resp = httpx.Response(
            status_code=500,
            headers={"content-type": "application/json"},
            content=b'{"message": "Internal Server Error"}',
            request=httpx.Request("POST", "https://api.notion.com/v1/search"),
        )
        # max_retries=0 so we only need a single response in the queue
        _patch_notion_client(monkeypatch, [resp])
        adapter = NotionConnectorAdapter(max_retries=0)
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


class TestRegistration:
    def test_notion_registered_in_provider_registry(self) -> None:
        from app.domains.connectors.services.provider_registry import default_provider_registry

        provider = default_provider_registry.get("notion")
        assert provider is not None
        assert provider.display_name == "Notion"

    def test_notion_adapter_registered_in_sync_registry(self) -> None:
        import app.domains.connectors.providers  # noqa: F401 – triggers registration
        from app.domains.connectors.services.provider_adapter import default_sync_adapter_registry

        adapter = default_sync_adapter_registry.get("notion")
        assert isinstance(adapter, NotionConnectorAdapter)

    def test_notion_provider_has_oauth_config(self) -> None:
        from app.domains.connectors.services.provider_registry import default_provider_registry

        provider = default_provider_registry.require("notion")
        assert provider.oauth is not None
        assert "notion.com" in provider.oauth.authorization_endpoint

    def test_notion_provider_capabilities(self) -> None:
        from app.domains.connectors.services.provider_registry import default_provider_registry
        from app.models.enums import ConnectorCapability

        provider = default_provider_registry.require("notion")
        caps = provider.capabilities.capabilities
        assert ConnectorCapability.delta_sync in caps
        assert ConnectorCapability.attachments in caps
        assert ConnectorCapability.deletions in caps


class TestAdapterContract:
    @pytest.mark.asyncio
    async def test_contract_suite_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Contract suite calls list_items + delta_sync; mock HTTP to return empty results.
        empty_search = {
            "object": "list",
            "results": [],
            "has_more": False,
            "next_cursor": None,
        }
        # Provide two responses: one for list_items and one for delta_sync
        resp1 = _json_response(empty_search, url="https://api.notion.com/v1/search")
        resp2 = _json_response(empty_search, url="https://api.notion.com/v1/search")
        _patch_notion_client(monkeypatch, [resp1, resp2])
        adapter = NotionConnectorAdapter()
        await run_adapter_contract_suite(
            adapter,
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            credential=_BASE_CRED,
        )
