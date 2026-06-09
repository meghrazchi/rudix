from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.domains.connectors.providers.microsoft_sharepoint_onedrive.adapter import (
    MicrosoftSharePointOneDriveConnectorAdapter,
)
from app.domains.connectors.sdk.testing import run_adapter_contract_suite
from app.models.enums import ExternalItemType


def _json_response(data: dict[str, Any], *, url: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers={"content-type": "application/json"},
        content=json.dumps(data).encode(),
        request=httpx.Request("GET", url),
    )


def _bytes_response(content: bytes, *, url: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=content,
        request=httpx.Request("GET", url),
    )


class _FakeGraphClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeGraphClient:
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        self.calls.append(
            {
                "url": url,
                "params": params or {},
                "headers": headers or {},
                "follow_redirects": follow_redirects,
            }
        )
        if not self.responses:
            raise AssertionError(f"Unexpected request: {url}")
        return self.responses.pop(0)


def _patch_graph_client(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[httpx.Response],
) -> _FakeGraphClient:
    client = _FakeGraphClient(responses)

    def _factory(*_: object, **__: object) -> _FakeGraphClient:
        return client

    import app.domains.connectors.providers.microsoft_sharepoint_onedrive.adapter as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _factory)
    return client


@pytest.mark.asyncio
async def test_discover_sites_returns_paginated_sites(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _json_response(
        {
            "value": [
                {
                    "id": "site-1",
                    "displayName": "Engineering",
                    "webUrl": "https://contoso.sharepoint.com/sites/engineering",
                    "siteCollection": {"hostname": "contoso.sharepoint.com"},
                }
            ],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/sites?$skiptoken=abc",
        },
        url="https://graph.microsoft.com/v1.0/sites",
    )
    client = _patch_graph_client(monkeypatch, [response])
    adapter = MicrosoftSharePointOneDriveConnectorAdapter()

    items, next_cursor, has_more = await adapter.discover_sites(
        access_token="token",
        page_size=50,
    )

    assert has_more is True
    assert next_cursor == {"next_url": "https://graph.microsoft.com/v1.0/sites?$skiptoken=abc"}
    assert items[0]["provider_source_id"] == "site:site-1"
    assert client.calls[0]["params"]["search"] == "*"


@pytest.mark.asyncio
async def test_list_items_normalizes_file_metadata_and_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _json_response(
            {
                "value": [
                    {
                        "id": "file-1",
                        "name": "Architecture Overview.docx",
                        "webUrl": "https://contoso.sharepoint.com/:w:/r/sites/eng/Shared%20Documents/file-1",
                        "size": 1024,
                        "file": {
                            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        },
                        "parentReference": {
                            "id": "root",
                            "path": "/drives/drive-1/root:/Shared Documents",
                        },
                        "createdDateTime": "2026-01-01T10:00:00Z",
                        "lastModifiedDateTime": "2026-01-02T10:00:00Z",
                    }
                ],
            },
            url="https://graph.microsoft.com/v1.0/drives/drive-1/root/delta",
        ),
        _json_response(
            {
                "value": [
                    {
                        "id": "perm-1",
                        "roles": ["read"],
                        "grantedToV2": {"user": {"displayName": "Alice"}},
                    }
                ]
            },
            url="https://graph.microsoft.com/v1.0/drives/drive-1/items/file-1/permissions",
        ),
    ]
    _patch_graph_client(monkeypatch, responses)
    adapter = MicrosoftSharePointOneDriveConnectorAdapter()

    page = await adapter.list_items(
        organization_id=str(uuid4()),
        connection_id=str(uuid4()),
        external_source_id=None,
        provider_source_id="drive:drive-1",
        decrypted_credential={
            "access_token": "token",
            "permission_import_behavior": "direct",
        },
        cursor={},
        page_size=50,
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.provider_key == "microsoft-sharepoint-onedrive"
    assert item.provider_item_id == "item:drive-1:file-1"
    assert item.item_type == ExternalItemType.cloud_file
    assert item.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert item.permissions["entries"][0]["id"] == "perm-1"
    assert item.acl_hash is not None
    assert len(item.content_hash) == 64


@pytest.mark.asyncio
async def test_delta_sync_surfaces_deleted_items(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _json_response(
            {
                "value": [
                    {
                        "id": "file-2",
                        "deleted": {},
                        "name": "Old file.docx",
                    }
                ]
            },
            url="https://graph.microsoft.com/v1.0/drives/drive-1/root/delta",
        )
    ]
    _patch_graph_client(monkeypatch, responses)
    adapter = MicrosoftSharePointOneDriveConnectorAdapter()

    page = await adapter.delta_sync(
        organization_id=str(uuid4()),
        connection_id=str(uuid4()),
        external_source_id=None,
        provider_source_id="drive:drive-1",
        decrypted_credential={"access_token": "token", "permission_import_behavior": "none"},
        cursor={},
        page_size=50,
    )

    assert len(page.items) == 1
    assert page.items[0].provider_item_id == "item:drive-1:file-2"
    assert page.items[0].is_deleted is True


@pytest.mark.asyncio
async def test_download_file_content_exports_office_docs_to_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _json_response(
            {
                "id": "file-3",
                "name": "Quarterly Review.docx",
                "size": 1024,
                "file": {
                    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                },
            },
            url="https://graph.microsoft.com/v1.0/drives/drive-1/items/file-3",
        ),
        _bytes_response(
            b"%PDF-1.7\n% fake pdf",
            url="https://graph.microsoft.com/v1.0/drives/drive-1/items/file-3/content",
        ),
    ]
    _patch_graph_client(monkeypatch, responses)
    adapter = MicrosoftSharePointOneDriveConnectorAdapter()

    download = await adapter.download_file_content(
        provider_item_id="item:drive-1:file-3",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        decrypted_credential={"access_token": "token"},
    )

    assert download is not None
    content, filename, resolved_mime = download
    assert content.startswith(b"%PDF")
    assert filename.endswith(".pdf")
    assert resolved_mime == "application/pdf"


@pytest.mark.asyncio
async def test_contract_suite_passes_for_microsoft_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        _json_response(
            {
                "value": [
                    {
                        "id": "file-4",
                        "name": "Plan.pdf",
                        "webUrl": "https://contoso.sharepoint.com/sites/eng/Shared%20Documents/Plan.pdf",
                        "size": 42,
                        "file": {"mimeType": "application/pdf"},
                        "parentReference": {"id": "root", "path": "/drives/drive-1/root:"},
                    }
                ]
            },
            url="https://graph.microsoft.com/v1.0/drives/drive-1/root/delta",
        ),
        _json_response(
            {
                "value": [
                    {
                        "id": "file-4",
                        "name": "Plan.pdf",
                        "webUrl": "https://contoso.sharepoint.com/sites/eng/Shared%20Documents/Plan.pdf",
                        "size": 42,
                        "file": {"mimeType": "application/pdf"},
                        "parentReference": {"id": "root", "path": "/drives/drive-1/root:"},
                    }
                ]
            },
            url="https://graph.microsoft.com/v1.0/drives/drive-1/root/delta",
        ),
    ]
    _patch_graph_client(monkeypatch, responses)
    adapter = MicrosoftSharePointOneDriveConnectorAdapter()

    await run_adapter_contract_suite(
        adapter,
        organization_id=str(uuid4()),
        connection_id=str(uuid4()),
        credential={
            "access_token": "token",
            "permission_import_behavior": "none",
            "drive_ids": ["drive:drive-1"],
        },
    )
