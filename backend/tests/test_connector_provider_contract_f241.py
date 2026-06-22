"""Tests for F241: provider adapter contract suite and fake provider adapter.

Every adapter implementation must pass the same contract checks. This file:
  1. Tests FakeProviderAdapter itself (its configurable behaviors).
  2. Runs the contract harness against FakeProviderAdapter to prove the harness
     catches real violations.
  3. Covers GET /connectors/providers and GET /connectors/providers/{key}.

New adapters should add a test that calls run_adapter_contract_suite() against
a mock-HTTP version of the real adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domains.connectors.schemas.connectors import (
    NormalizedExternalItem,
)
from app.domains.connectors.sdk.content_hash import hash_text
from app.domains.connectors.sdk.testing import (
    AdapterContractError,
    FakeProviderAdapter,
    _make_item,
    run_adapter_contract_suite,
)
from app.domains.connectors.services.provider_adapter import (
    ConnectorAuthError,
    ConnectorRateLimitError,
    DeltaItem,
)
from app.models.enums import ExternalItemType, ExternalItemVisibility

pytestmark = pytest.mark.connector_contract

_ORG_ID = str(uuid4())
_CONN_ID = str(uuid4())


# ---------------------------------------------------------------------------
# _make_item helper
# ---------------------------------------------------------------------------


def test_make_item_produces_valid_normalized_item() -> None:
    item = _make_item(organization_id=_ORG_ID)
    assert item.provider_key == "fake"
    assert len(item.content_hash) == 64
    assert item.visibility == ExternalItemVisibility.org_wide


# ---------------------------------------------------------------------------
# FakeProviderAdapter — list_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_adapter_list_items_empty() -> None:
    adapter = FakeProviderAdapter()
    page = await adapter.list_items(
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential={},
        cursor={},
        page_size=10,
    )
    assert page.items == []
    assert not page.has_more
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_fake_adapter_list_items_single_page() -> None:
    items = [_make_item(organization_id=_ORG_ID, provider_item_id=f"item-{i}") for i in range(3)]
    adapter = FakeProviderAdapter(full_items=items)
    page = await adapter.list_items(
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential={},
        cursor={},
        page_size=10,
    )
    assert len(page.items) == 3
    assert not page.has_more


@pytest.mark.asyncio
async def test_fake_adapter_list_items_pagination() -> None:
    items = [_make_item(organization_id=_ORG_ID, provider_item_id=f"item-{i}") for i in range(5)]
    adapter = FakeProviderAdapter(full_items=items)

    page1 = await adapter.list_items(
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential={},
        cursor={},
        page_size=2,
    )
    assert len(page1.items) == 2
    assert page1.has_more
    assert page1.next_cursor == {"offset": 2}

    page2 = await adapter.list_items(
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential={},
        cursor=page1.next_cursor,
        page_size=2,
    )
    assert len(page2.items) == 2
    assert page2.has_more

    page3 = await adapter.list_items(
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential={},
        cursor=page2.next_cursor,
        page_size=2,
    )
    assert len(page3.items) == 1
    assert not page3.has_more


@pytest.mark.asyncio
async def test_fake_adapter_list_items_records_calls() -> None:
    adapter = FakeProviderAdapter()
    await adapter.list_items(
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential={},
        cursor={},
        page_size=10,
    )
    assert len(adapter.list_calls) == 1
    assert adapter.list_calls[0]["organization_id"] == _ORG_ID


@pytest.mark.asyncio
async def test_fake_adapter_list_items_raises_configured_error() -> None:
    error = ConnectorAuthError("token revoked")
    adapter = FakeProviderAdapter(raise_on_list=error)
    with pytest.raises(ConnectorAuthError):
        await adapter.list_items(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential={},
            cursor={},
            page_size=10,
        )


# ---------------------------------------------------------------------------
# FakeProviderAdapter — delta_sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_adapter_delta_sync_empty() -> None:
    adapter = FakeProviderAdapter()
    page = await adapter.delta_sync(
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential={},
        cursor={"token": "abc"},
        page_size=10,
    )
    assert page.items == []
    assert not page.has_more


@pytest.mark.asyncio
async def test_fake_adapter_delta_sync_with_upsert_and_delete() -> None:
    item = _make_item(organization_id=_ORG_ID, provider_item_id="page-1")
    delta_items = [
        DeltaItem(provider_item_id="page-1", is_deleted=False, item=item),
        DeltaItem(provider_item_id="page-old", is_deleted=True),
    ]
    adapter = FakeProviderAdapter(delta_items=delta_items)
    page = await adapter.delta_sync(
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential={},
        cursor={"token": "xyz"},
        page_size=10,
    )
    assert len(page.items) == 2
    assert page.items[0].is_deleted is False
    assert page.items[0].item == item
    assert page.items[1].is_deleted is True


@pytest.mark.asyncio
async def test_fake_adapter_delta_sync_raises_rate_limit() -> None:
    error = ConnectorRateLimitError("rate limited", retry_after_seconds=30)
    adapter = FakeProviderAdapter(raise_on_delta=error)
    with pytest.raises(ConnectorRateLimitError) as exc_info:
        await adapter.delta_sync(
            organization_id=_ORG_ID,
            connection_id=_CONN_ID,
            external_source_id=None,
            provider_source_id=None,
            decrypted_credential={},
            cursor={"token": "abc"},
            page_size=10,
        )
    assert exc_info.value.retry_after_seconds == 30


# ---------------------------------------------------------------------------
# Contract harness — passing adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_suite_passes_for_valid_adapter() -> None:
    item = _make_item(organization_id=_ORG_ID)
    delta_item = DeltaItem(provider_item_id=item.provider_item_id, is_deleted=False, item=item)
    adapter = FakeProviderAdapter(full_items=[item], delta_items=[delta_item])

    await run_adapter_contract_suite(
        adapter,
        organization_id=_ORG_ID,
        connection_id=_CONN_ID,
    )


# ---------------------------------------------------------------------------
# Contract harness — detecting violations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_catches_bad_content_hash() -> None:
    from unittest.mock import AsyncMock, patch

    from app.domains.connectors.services.provider_adapter import ItemPage

    item = _make_item(organization_id=_ORG_ID)
    bad_item = item.model_copy(update={"content_hash": "not-a-hash"})

    adapter = FakeProviderAdapter()

    with patch.object(
        adapter,
        "list_items",
        new=AsyncMock(return_value=ItemPage(items=[bad_item], has_more=False)),
    ):
        with pytest.raises(AdapterContractError, match="content_hash"):
            await run_adapter_contract_suite(
                adapter,
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
            )


@pytest.mark.asyncio
async def test_contract_catches_has_more_without_cursor() -> None:
    from unittest.mock import AsyncMock, patch

    from app.domains.connectors.services.provider_adapter import ItemPage

    adapter = FakeProviderAdapter()

    with patch.object(
        adapter,
        "list_items",
        new=AsyncMock(return_value=ItemPage(items=[], has_more=True, next_cursor=None)),
    ):
        with pytest.raises(AdapterContractError, match="has_more"):
            await run_adapter_contract_suite(
                adapter,
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
            )


@pytest.mark.asyncio
async def test_contract_catches_cursor_with_has_more_false() -> None:
    from unittest.mock import AsyncMock, patch

    from app.domains.connectors.services.provider_adapter import ItemPage

    adapter = FakeProviderAdapter()

    with patch.object(
        adapter,
        "list_items",
        new=AsyncMock(return_value=ItemPage(items=[], has_more=False, next_cursor={"offset": 1})),
    ):
        with pytest.raises(AdapterContractError, match="has_more"):
            await run_adapter_contract_suite(
                adapter,
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
            )


def test_normalized_item_rejects_comment_without_parent_id() -> None:
    from uuid import UUID

    from pydantic import ValidationError

    # NormalizedExternalItem raises at construction time for comments without parent
    with pytest.raises(ValidationError, match="provider_parent_id"):
        NormalizedExternalItem(
            organization_id=UUID(_ORG_ID),
            provider_key="fake",
            provider_item_id="comment-1",
            item_type=ExternalItemType.comment,
            title="A comment",
            source_url="https://fake.example.com/comment-1",
            content_hash=hash_text("comment text"),
            updated_at=datetime.now(UTC),
            sync_version=1,
            visibility=ExternalItemVisibility.org_wide,
            provider_parent_id=None,
        )


@pytest.mark.asyncio
async def test_contract_catches_delta_item_without_item_when_not_deleted() -> None:
    from unittest.mock import AsyncMock, patch

    from app.domains.connectors.services.provider_adapter import DeltaPage

    item = _make_item(organization_id=_ORG_ID)
    adapter = FakeProviderAdapter(full_items=[item])

    bad_delta = DeltaItem(provider_item_id="missing", is_deleted=False, item=None)
    with patch.object(
        adapter,
        "delta_sync",
        new=AsyncMock(return_value=DeltaPage(items=[bad_delta], has_more=False)),
    ):
        with pytest.raises(AdapterContractError, match="is_deleted=False"):
            await run_adapter_contract_suite(
                adapter,
                organization_id=_ORG_ID,
                connection_id=_CONN_ID,
            )


# ---------------------------------------------------------------------------
# Provider registry API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
def provider_client():
    """TestClient with get_current_principal stubbed to admin."""
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_principal
    from app.auth.models import AuthenticatedPrincipal
    from app.main import app
    from app.models.enums import OrganizationRole

    principal = AuthenticatedPrincipal(
        user_id=str(uuid4()),
        organization_id=str(uuid4()),
        roles=[OrganizationRole.admin.value],
        auth_provider="test",
    )

    app.dependency_overrides[get_current_principal] = lambda: principal
    yield TestClient(app, base_url="http://testserver/api/v1")
    app.dependency_overrides.pop(get_current_principal, None)


def test_list_providers_returns_all_registered(provider_client) -> None:
    from app.domains.connectors.services.provider_registry import default_provider_registry

    response = provider_client.get("/connectors/providers")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data

    registered_keys = {r.key for r in default_provider_registry.list()}
    returned_keys = {item["key"] for item in data["items"]}
    assert returned_keys == registered_keys


def test_list_providers_capability_structure(provider_client) -> None:
    response = provider_client.get("/connectors/providers")
    assert response.status_code == 200

    for item in response.json()["items"]:
        caps = item["capabilities"]
        assert isinstance(caps["capabilities"], list)
        assert isinstance(caps["rate_limits"], list)
        assert isinstance(caps["export_formats"], list)
        assert caps["auth_type"] in {"oauth2", "api_token", "service_account", "basic", "none"}


def test_get_provider_not_found(provider_client) -> None:
    response = provider_client.get("/connectors/providers/no_such_provider")
    assert response.status_code == 404


def test_get_provider_confluence_has_export_formats(provider_client) -> None:
    response = provider_client.get("/connectors/providers/confluence")
    assert response.status_code == 200
    data = response.json()
    formats = data["capabilities"]["export_formats"]
    assert len(formats) >= 1
    for ef in formats:
        assert "format" in ef
        assert "mime_type" in ef
    schema = data["config_schema"]
    assert schema["properties"]["space_keys"]["type"] == "array"
    assert schema["properties"]["cql_filter"]["type"] == "string"
    assert schema["properties"]["include_comments"]["type"] == "boolean"


def test_get_provider_google_drive_max_page_size(provider_client) -> None:
    response = provider_client.get("/connectors/providers/google_drive")
    assert response.status_code == 200
    assert response.json()["capabilities"]["max_page_size"] == 1000
