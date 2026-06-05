"""Tests for F244: Google Drive connector adapter.

Covers:
- Normalizer: file fields, metadata, content hash stability, URL construction
- Normalizer: folder fields, metadata, content hash stability
- Normalizer: Google-native type detection and export MIME mapping
- Normalizer: permission snapshot structure
- Normalizer: unsupported MIME type detection
- Adapter list_items: full drive scan (empty cursor)
- Adapter list_items: pagination via nextPageToken
- Adapter list_items: bearer token sent in Authorization header
- Adapter list_items: 401/403 → ConnectorAuthError
- Adapter list_items: 429 + Retry-After → ConnectorRateLimitError with retry_after_seconds
- Adapter list_items: 5xx → ConnectorProviderUnavailableError
- Adapter list_items: folder-scoped sync (provider_source_id)
- Adapter list_items: folder-scoped sync discovers and queues subfolders
- Adapter list_items: folder-scoped sync continues via folder_queue in cursor
- Adapter list_items: folder-scoped sync terminates when queue empty
- Adapter list_items: credential folder_ids used as root when no provider_source_id
- Adapter list_items: include_shared_drives passes allDrives params
- Adapter delta_sync: returns upsert DeltaItems for live files
- Adapter delta_sync: trashed files returned as is_deleted=True DeltaItems
- Adapter delta_sync: advances since cursor to latest modifiedTime
- Adapter delta_sync: modifiedTime filter sent in query when since present
- Adapter delta_sync: empty result preserves since cursor
- Adapter delta_sync: no since in cursor defaults to non-filtered query
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

from app.domains.connectors.providers.google_drive.adapter import (
    GoogleDriveConnectorAdapter,
    _get_root_folders,
)
from app.domains.connectors.providers.google_drive.normalizer import (
    NATIVE_EXPORT_MIME,
    UNSUPPORTED_MIME_TYPES,
    _file_content_hash,
    _folder_content_hash,
    is_google_folder,
    is_google_native,
    is_supported_file,
    normalize_file,
    normalize_folder,
)
from app.domains.connectors.sdk.testing import run_adapter_contract_suite
from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorProviderUnavailableError,
    ConnectorRateLimitError,
    DeltaItem,
    ItemPage,
)
from app.models.enums import ExternalItemType, ExternalItemVisibility

pytestmark = pytest.mark.google_drive_adapter

_ORG_ID = str(uuid4())
_CONN_ID = str(uuid4())
_ORG_UUID = UUID(_ORG_ID)
_CONN_UUID = UUID(_CONN_ID)

_BASE_CRED = {
    "auth_type": "oauth2",
    "access_token": "test-gdrive-token",
}

_SAMPLE_FILE = {
    "id": "file_abc123",
    "name": "Architecture Overview.pdf",
    "mimeType": "application/pdf",
    "parents": ["folder_root_001"],
    "modifiedTime": "2024-06-01T10:00:00.000Z",
    "createdTime": "2024-01-15T08:00:00.000Z",
    "webViewLink": "https://drive.google.com/file/d/file_abc123/view",
    "owners": [{"displayName": "Alice Smith", "emailAddress": "alice@example.com"}],
    "permissions": [
        {"id": "anyone", "type": "anyone", "role": "reader"},
        {"id": "user_001", "type": "user", "role": "writer", "emailAddress": "alice@example.com"},
    ],
    "size": "204800",
    "md5Checksum": "d8e8fca2dc0f896fd7cb4cb0031ba249",
    "trashed": False,
    "driveId": None,
}

_SAMPLE_GOOGLE_DOC = {
    "id": "doc_xyz789",
    "name": "Project Spec",
    "mimeType": "application/vnd.google-apps.document",
    "parents": ["folder_root_001"],
    "modifiedTime": "2024-06-02T14:00:00.000Z",
    "createdTime": "2024-02-01T09:00:00.000Z",
    "webViewLink": "https://docs.google.com/document/d/doc_xyz789/edit",
    "owners": [{"displayName": "Bob Jones", "emailAddress": "bob@example.com"}],
    "permissions": [],
    "size": None,
    "md5Checksum": None,
    "trashed": False,
    "driveId": None,
}

_SAMPLE_FOLDER = {
    "id": "folder_root_001",
    "name": "Engineering Docs",
    "mimeType": "application/vnd.google-apps.folder",
    "parents": ["root"],
    "modifiedTime": "2024-05-20T12:00:00.000Z",
    "createdTime": "2024-01-01T00:00:00.000Z",
    "webViewLink": "https://drive.google.com/drive/folders/folder_root_001",
    "owners": [{"displayName": "Alice Smith", "emailAddress": "alice@example.com"}],
    "permissions": [],
    "trashed": False,
    "driveId": None,
}

_SAMPLE_SUBFOLDER = {
    "id": "folder_sub_002",
    "name": "Designs",
    "mimeType": "application/vnd.google-apps.folder",
    "parents": ["folder_root_001"],
    "modifiedTime": "2024-05-25T10:00:00.000Z",
    "createdTime": "2024-02-10T00:00:00.000Z",
    "webViewLink": "https://drive.google.com/drive/folders/folder_sub_002",
    "owners": [],
    "permissions": [],
    "trashed": False,
    "driveId": None,
}

_TRASHED_FILE = {
    "id": "file_deleted_999",
    "name": "Old Report.docx",
    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "parents": ["folder_root_001"],
    "modifiedTime": "2024-06-03T09:00:00.000Z",
    "createdTime": "2024-03-01T00:00:00.000Z",
    "webViewLink": "https://drive.google.com/file/d/file_deleted_999/view",
    "owners": [],
    "permissions": [],
    "size": "51200",
    "md5Checksum": "abc123def456",
    "trashed": True,
    "driveId": None,
}

_LIST_RESPONSE_SINGLE = {"files": [_SAMPLE_FILE], "nextPageToken": None}
_LIST_RESPONSE_EMPTY = {"files": [], "nextPageToken": None}
_LIST_RESPONSE_WITH_TOKEN = {
    "files": [_SAMPLE_FILE, _SAMPLE_GOOGLE_DOC],
    "nextPageToken": "token_page_2",
}
_LIST_RESPONSE_FOLDER_CONTENTS = {
    "files": [_SAMPLE_SUBFOLDER, _SAMPLE_FILE],
    "nextPageToken": None,
}


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_httpx_response(data: dict, *, status: int = 200) -> httpx.Response:
    content = json.dumps(data).encode()
    return httpx.Response(
        status_code=status,
        headers={"content-type": "application/json"},
        content=content,
        request=httpx.Request("GET", "https://www.googleapis.com/drive/v3/files"),
    )


def _make_httpx_error_response(*, status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        content=b'{"error": {"message": "error"}}',
        request=httpx.Request("GET", "https://www.googleapis.com/drive/v3/files"),
    )


def _patch_client(responses: list[httpx.Response]):
    """Return a mock AsyncClient that serves responses in order."""
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
# Normalizer — is_google_native / is_google_folder / is_supported_file
# ---------------------------------------------------------------------------


def test_is_google_native_document() -> None:
    assert is_google_native("application/vnd.google-apps.document")


def test_is_google_native_spreadsheet() -> None:
    assert is_google_native("application/vnd.google-apps.spreadsheet")


def test_is_google_native_presentation() -> None:
    assert is_google_native("application/vnd.google-apps.presentation")


def test_is_google_native_pdf_is_false() -> None:
    assert not is_google_native("application/pdf")


def test_is_google_native_none_is_false() -> None:
    assert not is_google_native(None)


def test_is_google_folder_true() -> None:
    assert is_google_folder("application/vnd.google-apps.folder")


def test_is_google_folder_false_for_file() -> None:
    assert not is_google_folder("application/pdf")


def test_is_supported_file_rejects_shortcut() -> None:
    assert not is_supported_file("application/vnd.google-apps.shortcut")


def test_is_supported_file_accepts_pdf() -> None:
    assert is_supported_file("application/pdf")


def test_is_supported_file_none_is_true() -> None:
    assert is_supported_file(None)


def test_native_export_mime_all_types_defined() -> None:
    expected = {
        "application/vnd.google-apps.document",
        "application/vnd.google-apps.spreadsheet",
        "application/vnd.google-apps.presentation",
        "application/vnd.google-apps.drawing",
        "application/vnd.google-apps.form",
        "application/vnd.google-apps.script",
    }
    assert set(NATIVE_EXPORT_MIME.keys()) == expected


# ---------------------------------------------------------------------------
# Normalizer — file
# ---------------------------------------------------------------------------


def test_normalize_file_basic_fields() -> None:
    item = normalize_file(
        _SAMPLE_FILE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.provider_key == "google_drive"
    assert item.provider_item_id == "file_abc123"
    assert item.item_type == ExternalItemType.cloud_file
    assert item.title == "Architecture Overview.pdf"
    assert item.source_url == "https://drive.google.com/file/d/file_abc123/view"
    assert item.visibility == ExternalItemVisibility.org_wide
    assert len(item.content_hash) == 64


def test_normalize_file_metadata() -> None:
    item = normalize_file(
        _SAMPLE_FILE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.metadata["mime_type"] == "application/pdf"
    assert item.metadata["owner_display_name"] == "Alice Smith"
    assert item.metadata["owner_email"] == "alice@example.com"
    assert item.metadata["size_bytes"] == "204800"
    assert item.metadata["md5_checksum"] == "d8e8fca2dc0f896fd7cb4cb0031ba249"
    assert item.metadata["parent_id"] == "folder_root_001"


def test_normalize_file_mime_type_on_item() -> None:
    item = normalize_file(
        _SAMPLE_FILE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.mime_type == "application/pdf"


def test_normalize_file_parent_id() -> None:
    item = normalize_file(
        _SAMPLE_FILE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.provider_parent_id == "folder_root_001"


def test_normalize_file_no_parents() -> None:
    f = {**_SAMPLE_FILE, "parents": []}
    item = normalize_file(
        f,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.provider_parent_id is None


def test_normalize_file_permissions_snapshot() -> None:
    item = normalize_file(
        _SAMPLE_FILE,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    entries = item.permissions["entries"]
    assert len(entries) == 2
    types = {e["type"] for e in entries}
    assert "anyone" in types
    assert "user" in types


def test_normalize_file_content_hash_stability() -> None:
    h1 = _file_content_hash(_SAMPLE_FILE)
    h2 = _file_content_hash(_SAMPLE_FILE)
    assert h1 == h2
    assert len(h1) == 64


def test_normalize_file_hash_changes_when_modified_time_changes() -> None:
    h1 = _file_content_hash(_SAMPLE_FILE)
    modified = {**_SAMPLE_FILE, "modifiedTime": "2024-12-01T00:00:00.000Z"}
    h2 = _file_content_hash(modified)
    assert h1 != h2


def test_normalize_file_url_fallback_without_webviewlink() -> None:
    f = {**_SAMPLE_FILE, "webViewLink": ""}
    item = normalize_file(
        f,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert "file_abc123" in item.source_url
    assert item.source_url.startswith("https://")


def test_normalize_google_doc_has_native_export_mime() -> None:
    item = normalize_file(
        _SAMPLE_GOOGLE_DOC,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.metadata.get("native_export_mime") == "text/plain"
    assert item.metadata.get("is_google_native") is True


def test_normalize_google_doc_mime_type_on_item() -> None:
    item = normalize_file(
        _SAMPLE_GOOGLE_DOC,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.mime_type == "application/vnd.google-apps.document"


# ---------------------------------------------------------------------------
# Normalizer — folder
# ---------------------------------------------------------------------------


def test_normalize_folder_basic_fields() -> None:
    item = normalize_folder(
        _SAMPLE_FOLDER,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.provider_key == "google_drive"
    assert item.provider_item_id == "folder_root_001"
    assert item.item_type == ExternalItemType.folder
    assert item.title == "Engineering Docs"
    assert item.source_url == "https://drive.google.com/drive/folders/folder_root_001"


def test_normalize_folder_metadata() -> None:
    item = normalize_folder(
        _SAMPLE_FOLDER,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert item.metadata["folder_id"] == "folder_root_001"
    assert item.metadata["owner_display_name"] == "Alice Smith"
    assert item.metadata["parent_id"] == "root"


def test_normalize_folder_content_hash_stability() -> None:
    h1 = _folder_content_hash(_SAMPLE_FOLDER)
    h2 = _folder_content_hash(_SAMPLE_FOLDER)
    assert h1 == h2
    assert len(h1) == 64


def test_normalize_folder_url_fallback() -> None:
    f = {**_SAMPLE_FOLDER, "webViewLink": ""}
    item = normalize_folder(
        f,
        organization_id=_ORG_UUID,
        connection_id=_CONN_UUID,
        external_source_id=None,
        sync_version=1,
    )
    assert "folder_root_001" in item.source_url
    assert "folders" in item.source_url


# ---------------------------------------------------------------------------
# _get_root_folders helper
# ---------------------------------------------------------------------------


def test_get_root_folders_from_provider_source_id() -> None:
    assert _get_root_folders("folder_123", {}) == ["folder_123"]


def test_get_root_folders_from_credential_folder_ids() -> None:
    cred = {"folder_ids": ["folder_a", "folder_b"]}
    assert _get_root_folders(None, cred) == ["folder_a", "folder_b"]


def test_get_root_folders_provider_source_id_takes_precedence() -> None:
    cred = {"folder_ids": ["folder_a"]}
    assert _get_root_folders("override_folder", cred) == ["override_folder"]


def test_get_root_folders_none_when_absent() -> None:
    assert _get_root_folders(None, {}) is None


def test_get_root_folders_strips_whitespace() -> None:
    cred = {"folder_ids": ["  folder_a  ", "  folder_b  "]}
    result = _get_root_folders(None, cred)
    assert result == ["folder_a", "folder_b"]


# ---------------------------------------------------------------------------
# Adapter — list_items (full drive scan)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_full_scan_single_file() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_SINGLE)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=100,
        )

    assert isinstance(page, ItemPage)
    assert len(page.items) == 1
    assert page.items[0].provider_item_id == "file_abc123"
    assert page.items[0].item_type == ExternalItemType.cloud_file
    assert not page.has_more


@pytest.mark.asyncio
async def test_list_items_full_scan_empty() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_EMPTY)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=100,
        )

    assert page.items == []
    assert not page.has_more
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_list_items_pagination_has_more() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_WITH_TOKEN)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

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
    assert page.next_cursor["page_token"] == "token_page_2"
    assert len(page.items) == 2


@pytest.mark.asyncio
async def test_list_items_uses_page_token_from_cursor() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_SINGLE)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"page_token": "resume_token_xyz"},
            page_size=50,
        )

    assert captured_params.get("pageToken") == "resume_token_xyz"


@pytest.mark.asyncio
async def test_list_items_sends_bearer_token() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_EMPTY)
    captured_headers: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        captured_headers.update(headers or {})
        return mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )

    assert captured_headers.get("Authorization") == "Bearer test-gdrive-token"


@pytest.mark.asyncio
async def test_list_items_include_shared_drives_sends_correct_params() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_EMPTY)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        cred = {**_BASE_CRED, "include_shared_drives": True}
        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=cred,
            cursor={},
            page_size=10,
        )

    assert captured_params.get("corpora") == "allDrives"
    assert captured_params.get("includeItemsFromAllDrives") == "true"
    assert captured_params.get("supportsAllDrives") == "true"


# ---------------------------------------------------------------------------
# Adapter — list_items error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_401_raises_auth_error() -> None:
    adapter = GoogleDriveConnectorAdapter()
    err = _make_httpx_error_response(status=401)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=err)
        mock_cls.return_value = mock_client

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
    adapter = GoogleDriveConnectorAdapter()
    err = _make_httpx_error_response(status=403)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=err)
        mock_cls.return_value = mock_client

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
    adapter = GoogleDriveConnectorAdapter()
    err = _make_httpx_error_response(status=429, headers={"Retry-After": "45"})

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=err)
        mock_cls.return_value = mock_client

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
    adapter = GoogleDriveConnectorAdapter()
    err = _make_httpx_error_response(status=500)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=err)
        mock_cls.return_value = mock_client

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
# Adapter — list_items folder-scoped (recursive traversal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_items_folder_scoped_queries_correct_parent() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_FOLDER_CONTENTS)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id="folder_root_001",
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=50,
        )

    assert "'folder_root_001' in parents" in captured_params.get("q", "")


@pytest.mark.asyncio
async def test_list_items_folder_scoped_enqueues_discovered_subfolders() -> None:
    adapter = GoogleDriveConnectorAdapter()
    # Response contains a subfolder + a file
    mock_response = _make_httpx_response(_LIST_RESPONSE_FOLDER_CONTENTS)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id="folder_root_001",
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=50,
        )

    # Subfolder should be queued → has_more True
    assert page.has_more
    assert page.next_cursor is not None
    assert "folder_sub_002" in page.next_cursor.get("folder_queue", [])


@pytest.mark.asyncio
async def test_list_items_folder_scoped_returns_both_folder_and_file_items() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_FOLDER_CONTENTS)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id="folder_root_001",
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=50,
        )

    types = {i.item_type for i in page.items}
    assert ExternalItemType.folder in types
    assert ExternalItemType.cloud_file in types


@pytest.mark.asyncio
async def test_list_items_folder_scoped_continues_queue_from_cursor() -> None:
    adapter = GoogleDriveConnectorAdapter()
    # Second call processes the queued subfolder
    sub_contents = {"files": [_SAMPLE_FILE], "nextPageToken": None}
    mock_response = _make_httpx_response(sub_contents)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={
                "current_folder": None,
                "folder_queue": ["folder_sub_002"],
                "page_token": None,
            },
            page_size=50,
        )

    assert "'folder_sub_002' in parents" in captured_params.get("q", "")
    assert page.items[0].provider_item_id == "file_abc123"


@pytest.mark.asyncio
async def test_list_items_folder_scoped_terminates_when_queue_empty() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_EMPTY)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        page = await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={
                "current_folder": "some_folder",
                "folder_queue": [],
                "page_token": None,
            },
            page_size=50,
        )

    assert not page.has_more
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_list_items_credential_folder_ids_used_as_root() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_EMPTY)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        cred = {**_BASE_CRED, "folder_ids": ["cred_folder_001"]}
        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=cred,
            cursor={},
            page_size=10,
        )

    assert "'cred_folder_001' in parents" in captured_params.get("q", "")


# ---------------------------------------------------------------------------
# Adapter — delta_sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delta_sync_returns_upsert_items_for_live_files() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_SINGLE)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    live = [d for d in delta.items if not d.is_deleted]
    assert len(live) == 1
    assert live[0].item is not None
    assert live[0].item.provider_item_id == "file_abc123"


@pytest.mark.asyncio
async def test_delta_sync_trashed_file_returned_as_deleted() -> None:
    adapter = GoogleDriveConnectorAdapter()
    response_data = {"files": [_TRASHED_FILE], "nextPageToken": None}
    mock_response = _make_httpx_response(response_data)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    deleted = [d for d in delta.items if d.is_deleted]
    assert len(deleted) == 1
    assert deleted[0].provider_item_id == "file_deleted_999"
    assert deleted[0].item is None


@pytest.mark.asyncio
async def test_delta_sync_advances_since_cursor() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_SINGLE)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

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
    assert delta.next_cursor["since"] >= "2024-06-01"


@pytest.mark.asyncio
async def test_delta_sync_uses_since_in_query() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_EMPTY)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-06-01T00:00:00+00:00"},
            page_size=10,
        )

    assert "modifiedTime >" in captured_params.get("q", "")
    assert "2024-06-01" in captured_params.get("q", "")


@pytest.mark.asyncio
async def test_delta_sync_empty_result_preserves_since_cursor() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_EMPTY)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-06-01T00:00:00+00:00"},
            page_size=50,
        )

    assert delta.next_cursor is not None
    assert "since" in delta.next_cursor
    assert not delta.has_more


@pytest.mark.asyncio
async def test_delta_sync_no_since_falls_back_to_non_filtered_query() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_response = _make_httpx_response(_LIST_RESPONSE_EMPTY)
    captured_params: dict = {}

    async def fake_get(url, *, params=None, headers=None):
        if params:
            captured_params.update(params)
        return mock_response

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={},
            page_size=10,
        )

    assert "modifiedTime" not in captured_params.get("q", "")
    assert "trashed = false" in captured_params.get("q", "")


@pytest.mark.asyncio
async def test_delta_sync_folder_items_normalized_correctly() -> None:
    adapter = GoogleDriveConnectorAdapter()
    response_data = {"files": [_SAMPLE_FOLDER], "nextPageToken": None}
    mock_response = _make_httpx_response(response_data)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value = _patch_client([mock_response])

        delta = await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential=_BASE_CRED,
            cursor={"since": "2024-01-01T00:00:00+00:00"},
            page_size=50,
        )

    assert len(delta.items) == 1
    assert delta.items[0].item is not None
    assert delta.items[0].item.item_type == ExternalItemType.folder


# ---------------------------------------------------------------------------
# Adapter — provider contract suite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_drive_adapter_passes_contract_suite() -> None:
    adapter = GoogleDriveConnectorAdapter()
    mock_full = _make_httpx_response(_LIST_RESPONSE_SINGLE)
    mock_empty = _make_httpx_response(_LIST_RESPONSE_EMPTY)

    call_count = 0

    async def fake_get(url, *, params=None, headers=None):
        nonlocal call_count
        call_count += 1
        return mock_full if call_count == 1 else mock_empty

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get
        mock_cls.return_value = mock_client

        await run_adapter_contract_suite(
            adapter,
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            credential=_BASE_CRED,
        )


# ---------------------------------------------------------------------------
# Adapter registration
# ---------------------------------------------------------------------------


def test_google_drive_adapter_is_registered() -> None:
    from app.domains.connectors.services.provider_adapter import default_sync_adapter_registry
    import app.domains.connectors.providers  # noqa: F401

    adapter = default_sync_adapter_registry.get("google_drive")
    assert adapter is not None
    assert isinstance(adapter, GoogleDriveConnectorAdapter)
