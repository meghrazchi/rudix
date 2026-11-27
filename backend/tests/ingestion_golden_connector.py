"""Connector rows for the connector-backed ingestion golden scenario (R06-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_source import SourceDocument
from app.models.enums import ConnectorAuthType, ExternalItemType

PROVIDER_KEY = "golden_drive"


async def seed_connector_item(
    session: AsyncSession, organization_id: UUID, user_id: UUID, suffix: str
) -> UUID:
    provider = (
        await session.execute(
            select(ConnectorProvider).where(ConnectorProvider.key == PROVIDER_KEY)
        )
    ).scalar_one_or_none()
    if provider is None:
        provider = ConnectorProvider(
            key=PROVIDER_KEY,
            display_name="Golden Drive",
            auth_type=ConnectorAuthType.oauth2.value,
            capabilities_json=[],
            config_schema_json={},
            rate_limits_json=[],
            export_formats_json=[],
            is_enabled=True,
        )
        session.add(provider)
        await session.flush()
    connection = ConnectorConnection(
        organization_id=organization_id,
        provider_id=provider.id,
        display_name="Golden Drive Connection",
        status="active",
        auth_config_json={},
        created_by_user_id=user_id,
    )
    session.add(connection)
    await session.flush()
    item = ExternalItem(
        organization_id=organization_id,
        connection_id=connection.id,
        provider_item_id="drive-item-1",
        item_type=ExternalItemType.cloud_file.value,
        title="Leave Policy",
        source_url="https://drive.example.test/items/leave-policy",
        content_hash="a" * 64,
        source_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        sync_version=3,
        visibility="org_wide",
        metadata_json={},
        permissions_json={"entries": [{"type": "user", "role": "reader"}]},
    )
    session.add(item)
    await session.flush()
    return item.id


async def seed_source_document(
    session: AsyncSession, organization_id: UUID, external_item_id: UUID, document_id: UUID
) -> None:
    session.add(
        SourceDocument(
            organization_id=organization_id,
            external_item_id=external_item_id,
            document_id=document_id,
            content_hash="b" * 64,
            sync_version=3,
            status="active",
        )
    )
    await session.flush()
