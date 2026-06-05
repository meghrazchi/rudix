from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.schemas.connectors import (
    NormalizedExternalItem,
    ProviderCapabilities,
    ProviderRegistration,
)
from app.domains.connectors.services.connector_service import (
    ConnectorBoundaryError,
    ConnectorPlatformService,
)
from app.domains.connectors.services.provider_registry import (
    ProviderRegistryError,
    build_default_provider_registry,
)
from app.models.collection import Collection
from app.models.enums import (
    ConnectorAuthType,
    ConnectorCapability,
    ExternalItemType,
    ExternalItemVisibility,
    OrganizationRole,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

HASH_A = "a" * 64


def test_provider_registry_supports_defaults_and_custom_provider() -> None:
    registry = build_default_provider_registry()

    jira = registry.require("jira")
    assert jira.capabilities.auth_type == ConnectorAuthType.oauth2
    assert jira.capabilities.supports(ConnectorCapability.comments)
    assert jira.capabilities.supports(ConnectorCapability.attachments)
    assert jira.capabilities.supports(ConnectorCapability.acls)

    confluence = registry.require("confluence")
    assert confluence.capabilities.supports(ConnectorCapability.folders)
    assert confluence.capabilities.supports(ConnectorCapability.export_formats)

    google_drive = registry.require("google_drive")
    assert google_drive.capabilities.supports(ConnectorCapability.delta_sync)
    assert google_drive.capabilities.supports(ConnectorCapability.folders)

    custom = ProviderRegistration(
        key="linear",
        display_name="Linear",
        capabilities=ProviderCapabilities(
            auth_type=ConnectorAuthType.oauth2,
            capabilities=frozenset(
                {
                    ConnectorCapability.comments,
                    ConnectorCapability.delta_sync,
                    ConnectorCapability.rate_limits,
                }
            ),
        ),
        config_schema={"type": "object", "additionalProperties": False},
    )
    registry.register(custom)
    assert registry.require("linear").display_name == "Linear"

    with pytest.raises(ProviderRegistryError):
        registry.register(custom)


@pytest.mark.parametrize(
    ("item_type", "provider_parent_id"),
    [
        (ExternalItemType.issue, None),
        (ExternalItemType.wiki_page, None),
        (ExternalItemType.cloud_file, None),
        (ExternalItemType.folder, None),
        (ExternalItemType.comment, "ISSUE-1"),
        (ExternalItemType.attachment, "PAGE-1"),
    ],
)
def test_normalized_external_item_accepts_shared_provider_shapes(
    item_type: ExternalItemType,
    provider_parent_id: str | None,
) -> None:
    item = _normalized_item(
        organization_id=uuid4(),
        item_type=item_type,
        provider_parent_id=provider_parent_id,
    )

    assert item.provider_item_id == "item-1"
    assert item.source_url == "https://example.test/item-1"
    assert item.content_hash == HASH_A
    assert item.sync_version == 1


def test_normalized_external_item_requires_stable_source_fields() -> None:
    with pytest.raises(ValidationError):
        _normalized_item(
            organization_id=uuid4(),
            content_hash="not-a-sha",
        )

    with pytest.raises(ValidationError):
        _normalized_item(
            organization_id=uuid4(),
            source_url="drive://item-1",
        )

    with pytest.raises(ValidationError):
        _normalized_item(
            organization_id=uuid4(),
            item_type=ExternalItemType.comment,
            provider_parent_id=None,
        )

    with pytest.raises(ValidationError):
        _normalized_item(
            organization_id=uuid4(),
            visibility=ExternalItemVisibility.collection,
            collection_id=None,
        )


@pytest.mark.asyncio
async def test_connector_service_enforces_tenant_and_collection_boundaries(
    db_session: AsyncSession,
) -> None:
    context = await _create_two_org_context(db_session)
    service = ConnectorPlatformService(repository=ConnectorRepository())

    connection = await service.create_connection(
        db_session,
        organization_id=context.org_one_id,
        provider_key="jira",
        display_name="Jira Production",
        collection_id=context.collection_one_id,
        created_by_user_id=context.user_one_id,
        external_account_id="jira-site-1",
    )
    source = await service.create_external_source(
        db_session,
        organization_id=context.org_one_id,
        connection_id=connection.id,
        provider_source_id="PROJECT",
        source_type="jira_project",
        name="Project",
        source_url="https://jira.example.test/projects/PROJECT",
    )
    item = await service.upsert_external_item(
        db_session,
        organization_id=context.org_one_id,
        item=_normalized_item(
            organization_id=context.org_one_id,
            connection_id=connection.id,
            external_source_id=source.id,
            collection_id=context.collection_one_id,
            item_type=ExternalItemType.issue,
            visibility=ExternalItemVisibility.collection,
        ),
    )

    assert item.organization_id == context.org_one_id
    assert item.collection_id == context.collection_one_id
    assert item.provider_item_id == "item-1"

    assert (
        await service.repository.get_connection(
            db_session,
            organization_id=context.org_two_id,
            connection_id=connection.id,
        )
        is None
    )
    with pytest.raises(ConnectorBoundaryError):
        await service.require_connection(db_session, context.org_two_id, connection.id)

    with pytest.raises(ConnectorBoundaryError):
        await service.create_external_source(
            db_session,
            organization_id=context.org_one_id,
            connection_id=connection.id,
            provider_source_id="OTHER",
            source_type="jira_project",
            name="Other",
            collection_id=context.collection_two_id,
        )

    with pytest.raises(ConnectorBoundaryError):
        await service.upsert_external_item(
            db_session,
            organization_id=context.org_two_id,
            item=_normalized_item(
                organization_id=context.org_one_id,
                connection_id=connection.id,
                external_source_id=source.id,
            ),
        )


class ConnectorTestContext:
    def __init__(
        self,
        *,
        org_one_id: UUID,
        org_two_id: UUID,
        user_one_id: UUID,
        user_two_id: UUID,
        collection_one_id: UUID,
        collection_two_id: UUID,
    ) -> None:
        self.org_one_id = org_one_id
        self.org_two_id = org_two_id
        self.user_one_id = user_one_id
        self.user_two_id = user_two_id
        self.collection_one_id = collection_one_id
        self.collection_two_id = collection_two_id


async def _create_two_org_context(db_session: AsyncSession) -> ConnectorTestContext:
    org_one = Organization(name=f"Connector Org {uuid4()}", slug=f"conn-org-{uuid4().hex[:8]}")
    org_two = Organization(name=f"Connector Org {uuid4()}", slug=f"conn-org-{uuid4().hex[:8]}")
    db_session.add_all([org_one, org_two])
    await db_session.flush()

    user_one = User(
        organization_id=org_one.id,
        external_auth_id=f"conn-user-{uuid4()}",
        email=f"conn-user-{uuid4().hex[:8]}@example.test",
    )
    user_two = User(
        organization_id=org_two.id,
        external_auth_id=f"conn-user-{uuid4()}",
        email=f"conn-user-{uuid4().hex[:8]}@example.test",
    )
    db_session.add_all([user_one, user_two])
    await db_session.flush()

    db_session.add_all(
        [
            OrganizationMember(
                organization_id=org_one.id,
                user_id=user_one.id,
                role=OrganizationRole.admin.value,
            ),
            OrganizationMember(
                organization_id=org_two.id,
                user_id=user_two.id,
                role=OrganizationRole.admin.value,
            ),
        ]
    )
    await db_session.flush()

    collection_one = Collection(
        organization_id=org_one.id,
        owner_id=user_one.id,
        name="Connector Collection One",
        description=None,
        access_policy="org_wide",
    )
    collection_two = Collection(
        organization_id=org_two.id,
        owner_id=user_two.id,
        name="Connector Collection Two",
        description=None,
        access_policy="org_wide",
    )
    db_session.add_all([collection_one, collection_two])
    await db_session.flush()

    return ConnectorTestContext(
        org_one_id=org_one.id,
        org_two_id=org_two.id,
        user_one_id=user_one.id,
        user_two_id=user_two.id,
        collection_one_id=collection_one.id,
        collection_two_id=collection_two.id,
    )


def _normalized_item(
    *,
    organization_id: UUID,
    provider_key: str = "jira",
    provider_item_id: str = "item-1",
    item_type: ExternalItemType = ExternalItemType.issue,
    source_url: str = "https://example.test/item-1",
    content_hash: str = HASH_A,
    sync_version: int = 1,
    connection_id: UUID | None = None,
    external_source_id: UUID | None = None,
    collection_id: UUID | None = None,
    provider_parent_id: str | None = None,
    visibility: ExternalItemVisibility = ExternalItemVisibility.org_wide,
) -> NormalizedExternalItem:
    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=provider_key,
        provider_item_id=provider_item_id,
        item_type=item_type,
        title="Item 1",
        source_url=source_url,
        content_hash=content_hash,
        updated_at=datetime.now(UTC),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        collection_id=collection_id,
        provider_parent_id=provider_parent_id,
        visibility=visibility,
    )
