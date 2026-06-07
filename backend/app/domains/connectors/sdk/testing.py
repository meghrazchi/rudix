"""Connector SDK testing utilities: FakeProviderAdapter and contract test harness.

Import from here in adapter test files to run the shared contract suite:

    from app.domains.connectors.sdk.testing import (
        FakeProviderAdapter,
        run_adapter_contract_suite,
    )
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.content_hash import hash_text
from app.domains.connectors.services.provider_adapter import (
    ConnectorProviderAdapter,
    DeltaItem,
    DeltaPage,
    ItemPage,
)
from app.models.enums import ExternalItemType, ExternalItemVisibility


def _make_item(
    *,
    organization_id: str,
    provider_key: str = "fake",
    provider_item_id: str | None = None,
    title: str = "Test Item",
    item_type: ExternalItemType = ExternalItemType.wiki_page,
    content: str = "hello",
    sync_version: int = 1,
) -> NormalizedExternalItem:
    """Build a minimal valid NormalizedExternalItem for tests."""
    from uuid import UUID

    return NormalizedExternalItem(
        organization_id=UUID(organization_id)
        if isinstance(organization_id, str)
        else organization_id,
        provider_key=provider_key,
        provider_item_id=provider_item_id or f"item-{uuid4().hex[:8]}",
        item_type=item_type,
        title=title,
        source_url=f"https://fake.example.com/items/{provider_item_id or uuid4().hex[:8]}",
        content_hash=hash_text(content),
        updated_at=datetime.now(UTC),
        sync_version=sync_version,
        visibility=ExternalItemVisibility.org_wide,
    )


@dataclass
class FakeProviderAdapter(ConnectorProviderAdapter):
    """Configurable fake adapter for contract tests and local development.

    Populate *full_items* for list_items() returns and *delta_items* for delta_sync().
    Set *raise_on_list* or *raise_on_delta* to simulate error conditions.
    """

    full_items: list[NormalizedExternalItem] = field(default_factory=list)
    delta_items: list[DeltaItem] = field(default_factory=list)
    raise_on_list: Exception | None = None
    raise_on_delta: Exception | None = None
    page_size_override: int | None = None

    list_calls: list[dict[str, Any]] = field(default_factory=list, init=False)
    delta_calls: list[dict[str, Any]] = field(default_factory=list, init=False)

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
        self.list_calls.append(
            {
                "organization_id": organization_id,
                "cursor": dict(cursor),
                "page_size": page_size,
            }
        )

        if self.raise_on_list is not None:
            raise self.raise_on_list

        effective_page_size = self.page_size_override or page_size
        offset = int(cursor.get("offset", 0))
        page_items = self.full_items[offset : offset + effective_page_size]
        next_offset = offset + len(page_items)
        has_more = next_offset < len(self.full_items)

        return ItemPage(
            items=page_items,
            next_cursor={"offset": next_offset} if has_more else None,
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
        self.delta_calls.append(
            {
                "organization_id": organization_id,
                "cursor": dict(cursor),
                "page_size": page_size,
            }
        )

        if self.raise_on_delta is not None:
            raise self.raise_on_delta

        return DeltaPage(
            items=self.delta_items,
            next_cursor=None,
            has_more=False,
        )


# ---------------------------------------------------------------------------
# Contract test harness — import and call run_adapter_contract_suite(adapter)
# from any adapter's test module to verify it satisfies the connector contract.
# ---------------------------------------------------------------------------


class AdapterContractError(AssertionError):
    """Raised when an adapter violates the connector provider contract."""


async def run_adapter_contract_suite(
    adapter: ConnectorProviderAdapter,
    *,
    organization_id: str,
    connection_id: str,
    credential: dict | None = None,
) -> None:
    """Run the full connector provider contract against *adapter*.

    Raises AdapterContractError on the first violation found.
    Call from a pytest test to verify a real adapter implementation.
    """
    cred = credential or {}
    empty_cursor: dict = {}

    # --- Contract 1: list_items returns ItemPage ---
    page = await adapter.list_items(
        organization_id=organization_id,
        connection_id=connection_id,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential=cred,
        cursor=empty_cursor,
        page_size=10,
    )
    if not isinstance(page, ItemPage):
        raise AdapterContractError(f"list_items() must return ItemPage, got {type(page).__name__}")

    # --- Contract 2: every item has a valid sha-256 content_hash ---
    for item in page.items:
        if not isinstance(item, NormalizedExternalItem):
            raise AdapterContractError(
                f"ItemPage.items must contain NormalizedExternalItem, got {type(item).__name__}"
            )
        _assert_valid_content_hash(item.content_hash)

    # --- Contract 3: cursor is JSON-serializable ---
    if page.next_cursor is not None:
        _assert_json_serializable(page.next_cursor, "next_cursor from list_items")

    # --- Contract 4: has_more is consistent with next_cursor ---
    if page.has_more and page.next_cursor is None:
        raise AdapterContractError(
            "has_more=True but next_cursor is None — must provide a cursor when has_more"
        )
    if not page.has_more and page.next_cursor is not None:
        raise AdapterContractError(
            "has_more=False but next_cursor is set — must be None when no more pages"
        )

    # --- Contract 5: delta_sync returns DeltaPage ---
    non_empty_cursor: dict = {"token": "contract-test-token"}
    delta = await adapter.delta_sync(
        organization_id=organization_id,
        connection_id=connection_id,
        external_source_id=None,
        provider_source_id=None,
        decrypted_credential=cred,
        cursor=non_empty_cursor,
        page_size=10,
    )
    if not isinstance(delta, DeltaPage):
        raise AdapterContractError(
            f"delta_sync() must return DeltaPage, got {type(delta).__name__}"
        )

    # --- Contract 6: delta items have correct structure ---
    for delta_item in delta.items:
        if not isinstance(delta_item, DeltaItem):
            raise AdapterContractError(
                f"DeltaPage.items must contain DeltaItem, got {type(delta_item).__name__}"
            )
        if not delta_item.is_deleted and delta_item.item is None:
            raise AdapterContractError("DeltaItem with is_deleted=False must have item set")
        if not delta_item.is_deleted and delta_item.item is not None:
            _assert_valid_content_hash(delta_item.item.content_hash)

    # --- Contract 7: comments/attachments have provider_parent_id ---
    all_items = list(page.items) + [
        d.item for d in delta.items if not d.is_deleted and d.item is not None
    ]
    for item in all_items:
        if item.item_type in {ExternalItemType.comment, ExternalItemType.attachment}:
            if item.provider_parent_id is None:
                raise AdapterContractError(
                    f"Item {item.provider_item_id!r} of type {item.item_type} "
                    "must have provider_parent_id set"
                )


def _assert_valid_content_hash(content_hash: str) -> None:
    hex_chars = set("0123456789abcdef")
    if len(content_hash) != 64 or any(c not in hex_chars for c in content_hash):
        raise AdapterContractError(
            f"content_hash must be a lowercase 64-char SHA-256 hex digest, got: {content_hash!r}"
        )


def _assert_json_serializable(data: Any, label: str) -> None:
    try:
        json.dumps(data)
    except (TypeError, ValueError) as exc:
        raise AdapterContractError(f"{label} must be JSON-serializable: {exc}") from exc
