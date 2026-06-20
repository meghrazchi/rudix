"""Batch-efficient utilities for building ResourceContext from the database — F332.

Callers pass pre-fetched or lazily-resolved DB data rather than individual ORM
queries per resource. Every public function is async and returns plain data that
the policy engine can consume without further I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policy_engine import ResourceContext, ResourceType
from app.models.authorization import ResourceAccessDeny, ResourceAccessGrant, SourceAclMapping
from app.models.collection import CollectionDocument
from app.models.connector import ExternalItem

# ── Collection membership ─────────────────────────────────────────────────────


async def get_subject_accessible_collection_ids(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    user_roles: list[str],
) -> list[str]:
    """Return IDs of collections the user may access, scoped to the org.

    Reuses CollectionRepository access-filter logic without loading full models.
    """
    from app.domains.collections.repositories.collections import CollectionRepository

    repo = CollectionRepository()
    collections = await repo.list(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=user_roles,
        limit=2000,
        offset=0,
    )
    return [str(c.id) for c in collections]


async def get_collection_ids_for_document(
    db_session: AsyncSession,
    *,
    document_id: UUID,
) -> list[str]:
    result = await db_session.execute(
        select(CollectionDocument.collection_id).where(
            CollectionDocument.document_id == document_id,
        )
    )
    return [str(row) for row in result.scalars()]


async def batch_get_collection_ids_for_documents(
    db_session: AsyncSession,
    *,
    document_ids: list[UUID],
) -> dict[str, list[str]]:
    """Return {doc_id_str: [collection_id_str, ...]} for a batch of documents."""
    if not document_ids:
        return {}
    result = await db_session.execute(
        select(CollectionDocument.document_id, CollectionDocument.collection_id).where(
            CollectionDocument.document_id.in_(document_ids),
        )
    )
    mapping: dict[str, list[str]] = {}
    for doc_id, col_id in result:
        mapping.setdefault(str(doc_id), []).append(str(col_id))
    return mapping


# ── Explicit grants / denies ──────────────────────────────────────────────────


def _NOW_UTC():
    return datetime.now(tz=UTC)


async def batch_get_explicit_grants(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    resource_type: ResourceType,
    resource_ids: list[str],
) -> dict[str, list[str]]:
    """Return {resource_id: [user_id, ...]} for active user-level grants."""
    if not resource_ids:
        return {}
    now = _NOW_UTC()
    result = await db_session.execute(
        select(ResourceAccessGrant.resource_id, ResourceAccessGrant.user_id).where(
            ResourceAccessGrant.organization_id == organization_id,
            ResourceAccessGrant.resource_type == resource_type,
            ResourceAccessGrant.resource_id.in_(resource_ids),
            ResourceAccessGrant.status == "active",
            ResourceAccessGrant.principal_type == "user",
            or_(
                ResourceAccessGrant.expires_at.is_(None),
                ResourceAccessGrant.expires_at > now,
            ),
        )
    )
    mapping: dict[str, list[str]] = {}
    for resource_id, user_id in result:
        if resource_id and user_id:
            mapping.setdefault(resource_id, []).append(str(user_id))
    return mapping


async def batch_get_explicit_denies(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    resource_type: ResourceType,
    resource_ids: list[str],
) -> dict[str, list[str]]:
    """Return {resource_id: [user_id, ...]} for active user-level denies."""
    if not resource_ids:
        return {}
    now = _NOW_UTC()
    result = await db_session.execute(
        select(ResourceAccessDeny.resource_id, ResourceAccessDeny.user_id).where(
            ResourceAccessDeny.organization_id == organization_id,
            ResourceAccessDeny.resource_type == resource_type,
            ResourceAccessDeny.resource_id.in_(resource_ids),
            ResourceAccessDeny.status == "active",
            ResourceAccessDeny.principal_type == "user",
            or_(
                ResourceAccessDeny.expires_at.is_(None),
                ResourceAccessDeny.expires_at > now,
            ),
        )
    )
    mapping: dict[str, list[str]] = {}
    for resource_id, user_id in result:
        if resource_id and user_id:
            mapping.setdefault(resource_id, []).append(str(user_id))
    return mapping


# ── Connector ACL ──────────────────────────────────────────────────────────────


async def get_connector_acl_user_ids(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    connector_connection_id: UUID,
) -> list[str]:
    """Return user IDs with active ACL-allow on the connector connection."""
    result = await db_session.execute(
        select(SourceAclMapping.user_id).where(
            SourceAclMapping.organization_id == organization_id,
            SourceAclMapping.connector_connection_id == connector_connection_id,
            SourceAclMapping.acl_effect == "allow",
            SourceAclMapping.is_active.is_(True),
            SourceAclMapping.principal_type == "user",
        )
    )
    return [str(row) for row in result.scalars() if row is not None]


async def batch_get_connector_acl_user_ids(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    connection_ids: list[UUID],
) -> dict[str, list[str]]:
    """Return {connection_id_str: [user_id, ...]} for a batch of connections."""
    if not connection_ids:
        return {}
    result = await db_session.execute(
        select(SourceAclMapping.connector_connection_id, SourceAclMapping.user_id).where(
            SourceAclMapping.organization_id == organization_id,
            SourceAclMapping.connector_connection_id.in_(connection_ids),
            SourceAclMapping.acl_effect == "allow",
            SourceAclMapping.is_active.is_(True),
            SourceAclMapping.principal_type == "user",
        )
    )
    mapping: dict[str, list[str]] = {}
    for conn_id, user_id in result:
        if conn_id and user_id:
            mapping.setdefault(str(conn_id), []).append(str(user_id))
    return mapping


async def get_connection_id_for_external_item(
    db_session: AsyncSession,
    *,
    external_item_id: UUID,
) -> UUID | None:
    result = await db_session.execute(
        select(ExternalItem.connection_id).where(ExternalItem.id == external_item_id)
    )
    return result.scalar_one_or_none()


async def batch_get_connection_ids_for_external_items(
    db_session: AsyncSession,
    *,
    external_item_ids: list[UUID],
) -> dict[str, str]:
    """Return {external_item_id_str: connection_id_str}."""
    if not external_item_ids:
        return {}
    result = await db_session.execute(
        select(ExternalItem.id, ExternalItem.connection_id).where(
            ExternalItem.id.in_(external_item_ids),
        )
    )
    return {str(item_id): str(conn_id) for item_id, conn_id in result if conn_id is not None}


# ── High-level context builders ───────────────────────────────────────────────


async def build_document_resource_context(
    db_session: AsyncSession,
    *,
    document,
    organization_id: UUID,
    subject_accessible_collection_ids: list[str],
) -> ResourceContext:
    """Build a ResourceContext for a single Document, resolving ACL data.

    Suitable for single-resource operations (get, delete, upload). For lists
    use build_document_resource_contexts_batch() to avoid N+1 queries.
    """
    doc_id_str = str(document.id)
    collection_ids = await get_collection_ids_for_document(db_session, document_id=document.id)

    grants = await batch_get_explicit_grants(
        db_session,
        organization_id=organization_id,
        resource_type=ResourceType.document,
        resource_ids=[doc_id_str],
    )
    denies = await batch_get_explicit_denies(
        db_session,
        organization_id=organization_id,
        resource_type=ResourceType.document,
        resource_ids=[doc_id_str],
    )

    connector_allowed_user_ids: list[str] = []
    connector_id: str | None = None
    if document.connector_external_item_id is not None:
        connection_id = await get_connection_id_for_external_item(
            db_session, external_item_id=document.connector_external_item_id
        )
        if connection_id:
            connector_id = str(connection_id)
            connector_allowed_user_ids = await get_connector_acl_user_ids(
                db_session,
                organization_id=organization_id,
                connector_connection_id=connection_id,
            )

    return ResourceContext(
        resource_type=ResourceType.document,
        resource_id=doc_id_str,
        organization_id=str(organization_id),
        collection_ids=collection_ids,
        connector_id=connector_id,
        explicit_allow_user_ids=grants.get(doc_id_str, []),
        explicit_deny_user_ids=denies.get(doc_id_str, []),
        connector_allowed_user_ids=connector_allowed_user_ids,
        subject_accessible_collection_ids=subject_accessible_collection_ids,
    )


async def build_document_resource_contexts_batch(
    db_session: AsyncSession,
    *,
    documents: list,
    organization_id: UUID,
    subject_accessible_collection_ids: list[str],
) -> list[ResourceContext]:
    """Build ResourceContext for a list of Documents using batched DB queries.

    Runs 4 queries regardless of list length.
    """
    if not documents:
        return []

    doc_ids = [d.id for d in documents]
    doc_id_strings = [str(d.id) for d in documents]

    # Batch: collection memberships
    collections_by_doc = await batch_get_collection_ids_for_documents(
        db_session, document_ids=doc_ids
    )

    # Batch: explicit grants / denies
    grants_by_doc = await batch_get_explicit_grants(
        db_session,
        organization_id=organization_id,
        resource_type=ResourceType.document,
        resource_ids=doc_id_strings,
    )
    denies_by_doc = await batch_get_explicit_denies(
        db_session,
        organization_id=organization_id,
        resource_type=ResourceType.document,
        resource_ids=doc_id_strings,
    )

    # Batch: connector ACL for connector-backed documents
    ext_item_ids = [
        d.connector_external_item_id for d in documents if d.connector_external_item_id is not None
    ]
    ext_to_conn: dict[str, str] = {}
    conn_acl_by_conn: dict[str, list[str]] = {}
    if ext_item_ids:
        ext_to_conn = await batch_get_connection_ids_for_external_items(
            db_session, external_item_ids=ext_item_ids
        )
        unique_conn_ids = list({UUID(cid) for cid in ext_to_conn.values()})
        conn_acl_by_conn = await batch_get_connector_acl_user_ids(
            db_session,
            organization_id=organization_id,
            connection_ids=unique_conn_ids,
        )

    contexts: list[ResourceContext] = []
    for doc in documents:
        doc_id_str = str(doc.id)
        connector_id: str | None = None
        connector_allowed: list[str] = []
        if doc.connector_external_item_id is not None:
            conn_id = ext_to_conn.get(str(doc.connector_external_item_id))
            if conn_id:
                connector_id = conn_id
                connector_allowed = conn_acl_by_conn.get(conn_id, [])

        contexts.append(
            ResourceContext(
                resource_type=ResourceType.document,
                resource_id=doc_id_str,
                organization_id=str(organization_id),
                collection_ids=collections_by_doc.get(doc_id_str, []),
                connector_id=connector_id,
                explicit_allow_user_ids=grants_by_doc.get(doc_id_str, []),
                explicit_deny_user_ids=denies_by_doc.get(doc_id_str, []),
                connector_allowed_user_ids=connector_allowed,
                subject_accessible_collection_ids=subject_accessible_collection_ids,
            )
        )
    return contexts


def build_collection_resource_context(
    *,
    collection,
    organization_id: UUID,
) -> ResourceContext:
    """Build a ResourceContext for a Collection.

    Collections don't currently support row-level grants/denies — access is
    governed by the collection's access_policy and CollectionAccessGrant rows
    (enforced by CollectionRepository). We pass an empty explicit allow/deny
    list and let rule 11 (role_permission) decide.
    """
    return ResourceContext(
        resource_type=ResourceType.collection,
        resource_id=str(collection.id),
        organization_id=str(organization_id),
    )


def build_connector_resource_context(
    *,
    connection,
    organization_id: UUID,
) -> ResourceContext:
    """Build a ResourceContext for a ConnectorConnection."""
    return ResourceContext(
        resource_type=ResourceType.connector,
        resource_id=str(connection.id),
        organization_id=str(organization_id),
    )
