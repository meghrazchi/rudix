"""R04-13: lookups and workflows moved out of the documents/admin routers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.documents.sample_dataset import (
    _SAMPLE_DOCUMENTS,
    load_sample_dataset_workflow,
)
from app.domains.documents.repositories.document_lookups import DocumentLookupRepository
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.authorization import SourceAclMapping
from app.models.collection import Collection
from app.models.connector_source import SourceDocument
from tests.list_endpoint_seed import (
    seed_collection,
    seed_connection,
    seed_document,
    seed_tenant,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]

lookups = DocumentLookupRepository()


def _acl(tenant_org: object, connection_id: object, user_id: object, **overrides: object):
    values: dict[str, object] = {
        "organization_id": tenant_org,
        "connector_connection_id": connection_id,
        "source_type": "page",
        "source_id": "s1",
        "user_id": user_id,
        "principal_type": "user",
        "principal_value": "u",
        "action": "read_only",
        "acl_effect": "allow",
        "is_active": True,
    }
    values.update(overrides)
    return SourceAclMapping(**values)


async def test_user_source_acl_allow_requires_active_allow_for_user_and_org(
    db_session: AsyncSession,
) -> None:
    tenant = await seed_tenant(db_session)
    other = await seed_tenant(db_session)
    connection, _ = await seed_connection(db_session, tenant, indexed_documents=0)

    async def allowed(org_id: object = tenant.org_id) -> bool:
        return await lookups.has_user_source_acl_allow(
            db_session,
            organization_id=org_id,  # type: ignore[arg-type]
            user_id=tenant.user.id,
            connection_id=connection.id,
        )

    assert await allowed() is False
    db_session.add(_acl(tenant.org_id, connection.id, tenant.user.id, is_active=False))
    await db_session.flush()
    assert await allowed() is False
    db_session.add(_acl(tenant.org_id, connection.id, tenant.user.id, acl_effect="deny"))
    await db_session.flush()
    assert await allowed() is False
    db_session.add(_acl(tenant.org_id, connection.id, tenant.user.id))
    await db_session.flush()
    assert await allowed() is True
    # Organization isolation: the same grant never counts for another organization.
    assert await allowed(other.org_id) is False


async def test_collections_for_documents_skips_archived_and_orders_by_name(
    db_session: AsyncSession,
) -> None:
    tenant = await seed_tenant(db_session)
    document, _ = await seed_document(db_session, tenant, chunks=0)
    bare, _ = await seed_document(db_session, tenant, chunks=0)
    live_id = await seed_collection(db_session, tenant, documents=[document])
    archived_id = await seed_collection(db_session, tenant, documents=[document])
    archived = await db_session.get(Collection, archived_id)
    assert archived is not None
    archived.is_archived = True
    await db_session.flush()

    rows = await lookups.collections_for_documents(db_session, document_ids=[document.id, bare.id])

    assert [(row[0], row[1]) for row in rows] == [(document.id, live_id)]


async def test_source_providers_for_documents_maps_connector_documents(
    db_session: AsyncSession,
) -> None:
    tenant = await seed_tenant(db_session)
    connection, documents = await seed_connection(db_session, tenant, indexed_documents=1)
    plain, _ = await seed_document(db_session, tenant, chunks=0)
    from sqlalchemy import select

    from app.models.connector import ExternalItem

    item = (await db_session.execute(select(ExternalItem))).scalars().first()
    assert item is not None
    db_session.add(
        SourceDocument(
            organization_id=tenant.org_id,
            external_item_id=item.id,
            document_id=documents[0].id,
            content_hash="a" * 64,
            sync_version=1,
        )
    )
    await db_session.flush()

    providers = await lookups.source_providers_for_documents(
        db_session, document_ids=[documents[0].id, plain.id]
    )

    assert providers == {documents[0].id: "confluence"}
    assert connection.id is not None


async def test_sample_docs_enabled_and_filenames(db_session: AsyncSession) -> None:
    tenant = await seed_tenant(db_session)
    assert await lookups.sample_docs_enabled(db_session, organization_id=tenant.org_id) is False
    assert await lookups.sample_docs_enabled(db_session, organization_id=uuid4()) is False

    tenant.organization.sample_docs_enabled = True
    await db_session.flush()
    assert await lookups.sample_docs_enabled(db_session, organization_id=tenant.org_id) is True
    assert (
        await lookups.sample_document_filenames(db_session, organization_id=tenant.org_id) == set()
    )


async def test_sample_dataset_workflow_is_idempotent_and_gated(
    db_session: AsyncSession,
) -> None:
    tenant = await seed_tenant(db_session)
    with pytest.raises(HTTPException) as denied:
        await load_sample_dataset_workflow(
            db_session, organization_id=tenant.org_id, user_id=tenant.user.id
        )
    assert denied.value.status_code == 403

    tenant.organization.sample_docs_enabled = True
    await db_session.flush()
    first = await load_sample_dataset_workflow(
        db_session, organization_id=tenant.org_id, user_id=tenant.user.id
    )
    second = await load_sample_dataset_workflow(
        db_session, organization_id=tenant.org_id, user_id=tenant.user.id
    )

    assert first.created == len(_SAMPLE_DOCUMENTS)
    assert first.skipped == 0
    assert second.created == 0
    assert second.skipped == len(_SAMPLE_DOCUMENTS)


async def test_count_org_documents_summary_matches_per_status_counts(
    db_session: AsyncSession,
) -> None:
    tenant = await seed_tenant(db_session)
    other = await seed_tenant(db_session)
    indexed, _ = await seed_document(db_session, tenant, chunks=0, status="indexed")
    indexed.chunk_count = 7
    await seed_document(db_session, tenant, chunks=0, status="failed")
    await seed_document(db_session, tenant, chunks=0, status="deleted")
    foreign, _ = await seed_document(db_session, other, chunks=0, status="indexed")
    foreign.chunk_count = 99
    await db_session.flush()
    repository = DocumentRepository()

    assert await repository.count_org_documents_summary(
        db_session, organization_id=tenant.org_id
    ) == (2, 1, 7)
    assert await repository.count_org_documents_summary(db_session, organization_id=uuid4()) == (
        0,
        0,
        0,
    )
