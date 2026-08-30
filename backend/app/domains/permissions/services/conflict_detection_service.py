"""Conflict detection service — F335, extended by F354.

Scans an organisation's grants, denies, and ACL mappings for permission
conflicts. Writes new AuthorizationConflict rows for each novel conflict found.

Detected conflict types
-----------------------
1. role_allow_resource_deny          — active grant + active deny on same
                                       principal / resource / action triple
2. orphaned_acl_mapping              — SourceAclMapping whose connector_connection_id
                                       no longer has any active connector row
3. stale_grant_removed_connector     — active grant for connector resource_type
                                       whose target connector no longer exists
4. stale_grant_deleted_resource      — active grant references a document that
                                       no longer exists
5. collection_allow_connector_acl_deny — a connector connection has a real
                                       (non-empty) ACL allow-list, but a document
                                       it backs also belongs to a collection that
                                       grants access to users outside that
                                       allow-list. PolicyEngine's rule 8
                                       (collection_allow) is evaluated before
                                       rule 9 (connector_acl) and short-circuits
                                       it, so those users reach the document
                                       despite the connector ACL restriction.
6. citation_visible_source_hidden    — a citation remains visible in a chat
                                       transcript but its source document would
                                       now be denied to the citing user (the
                                       backing connector connection was revoked,
                                       or an explicit deny was added since)
7. graph_entity_visible_evidence_inaccessible — a graph entity is visible
                                       org-wide (PolicyEngine does not gate
                                       graph_entity by collection) while its
                                       evidence is sourced from a document in a
                                       restricted collection (graph_evidence
                                       *is* collection-gated) — a structural
                                       asymmetry, not a per-user decision, so
                                       these conflicts use subject_type='collection'

Declared but intentionally out of scope for F354 (not detected by scan()):
feature_deny_active_grant, explicit_grant_conflicts_role_deny — not called for
by any F354 acceptance criterion.

Severity mapping (API ↔ DB)
---------------------------
  info          ↔  low
  warning       ↔  medium
  blocking      ↔  high
  security_risk ↔  critical
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policy_engine import ResourceType
from app.auth.resource_context_builder import (
    batch_get_collection_ids_for_documents,
    batch_get_connection_ids_for_external_items,
    batch_get_explicit_denies,
)
from app.domains.graph.repositories.evidence_repository import EvidenceRepository
from app.domains.permissions.repositories.conflicts import ConflictsRepository
from app.domains.permissions.schemas.conflicts import ScanResult
from app.models.authorization import (
    ResourceAccessDeny,
    ResourceAccessGrant,
    SourceAclMapping,
)
from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.collection import Collection, CollectionAccessGrant, CollectionDocument
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.document import Document
from app.models.organization_member import OrganizationMember
from app.models.permissions import ROLE_PERMISSIONS, PermissionType

_repo = ConflictsRepository()
_evidence_repo = EvidenceRepository()

# Roles that bypass all resource-level checks via PolicyEngine rule 5
# (owner_admin_override) — not a meaningful "conflict" if they reach a
# connector-ACL-restricted document, since that's true of every resource.
_ADMIN_ROLE_NAMES = frozenset({"owner", "admin"})


# ── Remediation library ────────────────────────────────────────────────────────

_REMEDIATION: dict[str, list[str]] = {
    "role_allow_resource_deny": [
        "Review the explicit deny entry and remove it if access should be granted.",
        "If the deny is intentional, revoke the conflicting grant.",
        "Consider whether this principal requires a narrower role instead of a broad grant.",
    ],
    "collection_allow_connector_acl_deny": [
        "Re-sync the connector ACL to ensure collection-level access is reflected.",
        "Remove the collection grant if the connector ACL restriction is correct.",
        "Contact the connector administrator to update ACL permissions upstream.",
    ],
    "stale_grant_deleted_resource": [
        "Revoke the grant as the target resource no longer exists.",
        "Audit other grants from the same principal for additional stale entries.",
    ],
    "stale_grant_removed_connector": [
        "Revoke the connector grant and re-create it if the connector is re-connected.",
        "Verify the connector is still active before granting connector-scoped access.",
    ],
    "orphaned_acl_mapping": [
        "Remove ACL mappings for connectors that have been deleted or disconnected.",
        "Re-run the connector sync to generate fresh ACL mappings.",
    ],
    "feature_deny_active_grant": [
        "If the feature is intentionally disabled, revoke conflicting explicit grants.",
        "Enable the feature for this organisation if grant-level access is correct.",
    ],
    "explicit_grant_conflicts_role_deny": [
        "Review whether the explicit grant is intentional given the role restriction.",
        "Downgrade the principal's role if the grant should be the limiting factor.",
    ],
    "citation_visible_source_hidden": [
        "Revoke citation-level access until the underlying source is also accessible.",
        "Grant the principal access to the source document backing the citation.",
    ],
    "graph_entity_visible_evidence_inaccessible": [
        "Ensure the principal has access to evidence documents backing the entity.",
        "If evidence documents are restricted, restrict graph entity access to match.",
    ],
}


def remediation_for(conflict_type: str) -> list[str]:
    return _REMEDIATION.get(conflict_type, ["Review this conflict manually with an administrator."])


# ── Scan result container ──────────────────────────────────────────────────────


@dataclass
class _ScanStats:
    conflicts_detected: int = 0
    conflicts_created: int = 0
    grants_scanned: int = 0
    denies_scanned: int = 0
    acl_scanned: int = 0


# ── Service ───────────────────────────────────────────────────────────────────


class ConflictDetectionService:
    async def scan(
        self,
        db: AsyncSession,
        organization_id: UUID,
    ) -> ScanResult:
        t0 = time.monotonic()
        stats = _ScanStats()

        # Load all active grants
        grants_q = select(ResourceAccessGrant).where(
            ResourceAccessGrant.organization_id == organization_id,
            ResourceAccessGrant.status == "active",
        )
        grants: list[ResourceAccessGrant] = list((await db.execute(grants_q)).scalars().all())
        stats.grants_scanned = len(grants)

        # Load all active denies
        denies_q = select(ResourceAccessDeny).where(
            ResourceAccessDeny.organization_id == organization_id,
            ResourceAccessDeny.status == "active",
        )
        denies: list[ResourceAccessDeny] = list((await db.execute(denies_q)).scalars().all())
        stats.denies_scanned = len(denies)

        # Load ACL mappings
        acl_q = select(SourceAclMapping).where(
            SourceAclMapping.organization_id == organization_id,
            SourceAclMapping.is_active.is_(True),
        )
        acls: list[SourceAclMapping] = list((await db.execute(acl_q)).scalars().all())
        stats.acl_scanned = len(acls)

        # ── 1. role_allow_resource_deny ──────────────────────────────────────
        deny_index: dict[tuple[str, str, str | None, str], ResourceAccessDeny] = {
            (d.principal_type, d.principal_value, d.resource_id, d.action): d for d in denies
        }
        for grant in grants:
            key = (grant.principal_type, grant.principal_value, grant.resource_id, grant.action)
            matching_deny = deny_index.get(key)
            if matching_deny and grant.resource_type == matching_deny.resource_type:
                stats.conflicts_detected += 1
                created = await self._upsert_conflict(
                    db,
                    organization_id=organization_id,
                    subject_type=grant.principal_type,
                    subject_value=grant.principal_value,
                    user_id=grant.user_id,
                    role_name=grant.role_name,
                    resource_type=grant.resource_type,
                    resource_id=grant.resource_id,
                    action=grant.action,
                    conflict_type="role_allow_resource_deny",
                    severity_db="high",
                    summary=(
                        f"Explicit grant {grant.id} allows {grant.principal_value} "
                        f"{grant.action} on {grant.resource_type}"
                        + (f"/{grant.resource_id}" if grant.resource_id else "")
                        + f", but deny {matching_deny.id} blocks the same access."
                    ),
                    grant_id=grant.id,
                    deny_id=matching_deny.id,
                    context={"grant_id": str(grant.id), "deny_id": str(matching_deny.id)},
                )
                if created:
                    stats.conflicts_created += 1

        # ── 2. orphaned_acl_mapping ─────────────────────────────────────────
        # Get active connector IDs
        active_connector_ids: set[str] = set()
        try:
            result = await db.execute(
                text(
                    "SELECT id::text FROM connector_connections WHERE organization_id = :org_id"
                ).bindparams(org_id=str(organization_id))
            )
            active_connector_ids = {row[0] for row in result.fetchall()}
        except Exception:
            pass  # Table may not exist in test environment

        for acl in acls:
            if acl.connector_connection_id is None:
                continue
            connector_str = str(acl.connector_connection_id)
            if connector_str not in active_connector_ids:
                stats.conflicts_detected += 1
                created = await self._upsert_conflict(
                    db,
                    organization_id=organization_id,
                    subject_type=acl.principal_type,
                    subject_value=acl.principal_value,
                    user_id=acl.user_id,
                    role_name=None,
                    resource_type=acl.source_type,
                    resource_id=acl.source_id,
                    action=acl.action,
                    conflict_type="orphaned_acl_mapping",
                    severity_db="low",
                    summary=(
                        f"ACL mapping for connector {acl.connector_connection_id} "
                        f"references a connector that no longer exists."
                    ),
                    context={"connector_connection_id": str(acl.connector_connection_id)},
                )
                if created:
                    stats.conflicts_created += 1

        # ── 3. stale_grant_removed_connector ────────────────────────────────
        connector_grants = [g for g in grants if g.resource_type == "connector"]
        for grant in connector_grants:
            if grant.resource_id and grant.resource_id not in active_connector_ids:
                stats.conflicts_detected += 1
                created = await self._upsert_conflict(
                    db,
                    organization_id=organization_id,
                    subject_type=grant.principal_type,
                    subject_value=grant.principal_value,
                    user_id=grant.user_id,
                    role_name=grant.role_name,
                    resource_type="connector",
                    resource_id=grant.resource_id,
                    action=grant.action,
                    conflict_type="stale_grant_removed_connector",
                    severity_db="medium",
                    summary=(
                        f"Grant {grant.id} references connector {grant.resource_id} "
                        "which no longer exists. This is a stale grant."
                    ),
                    grant_id=grant.id,
                    context={"grant_id": str(grant.id)},
                )
                if created:
                    stats.conflicts_created += 1

        # ── 4. stale_grant_deleted_resource ─────────────────────────────────
        # For document grants, check if the resource_id doc still exists
        document_grants = [
            g for g in grants if g.resource_type == "document" and g.resource_id is not None
        ]
        if document_grants:
            doc_ids = [
                UUID(g.resource_id) for g in document_grants if _is_valid_uuid(g.resource_id)
            ]
            if doc_ids:
                try:
                    result = await db.execute(
                        text(
                            "SELECT id::text FROM documents "
                            "WHERE id = ANY(:ids) AND organization_id = :org_id"
                        ).bindparams(ids=[str(d) for d in doc_ids], org_id=str(organization_id))
                    )
                    existing_doc_ids = {row[0] for row in result.fetchall()}
                    for grant in document_grants:
                        if grant.resource_id and grant.resource_id not in existing_doc_ids:
                            stats.conflicts_detected += 1
                            created = await self._upsert_conflict(
                                db,
                                organization_id=organization_id,
                                subject_type=grant.principal_type,
                                subject_value=grant.principal_value,
                                user_id=grant.user_id,
                                role_name=grant.role_name,
                                resource_type="document",
                                resource_id=grant.resource_id,
                                action=grant.action,
                                conflict_type="stale_grant_deleted_resource",
                                severity_db="low",
                                summary=(
                                    f"Grant {grant.id} references document "
                                    f"{grant.resource_id} which no longer exists."
                                ),
                                grant_id=grant.id,
                                context={"grant_id": str(grant.id)},
                            )
                            if created:
                                stats.conflicts_created += 1
                except Exception:
                    pass

        # ── 5-7. F354 additions ──────────────────────────────────────────────
        await self._detect_collection_allow_connector_acl_deny(db, organization_id, stats)
        await self._detect_citation_visible_source_hidden(db, organization_id, stats)
        await self._detect_graph_entity_visible_evidence_inaccessible(db, organization_id, stats)

        await db.flush()
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return ScanResult(
            conflicts_detected=stats.conflicts_detected,
            conflicts_created=stats.conflicts_created,
            scan_duration_ms=elapsed_ms,
            scanned_grants=stats.grants_scanned,
            scanned_denies=stats.denies_scanned,
            scanned_acl_mappings=stats.acl_scanned,
        )

    async def _detect_collection_allow_connector_acl_deny(
        self,
        db: AsyncSession,
        organization_id: UUID,
        stats: _ScanStats,
    ) -> None:
        """A connector connection has a real (non-empty) ACL allow-list, but a
        document it backs also belongs to a collection that grants access to
        users outside that allow-list.

        Per PolicyEngine.authorize(), rule 8 (collection_allow) runs before
        rule 9 (connector_acl) and returns immediately on a match — so any user
        who can reach the collection reaches the document regardless of the
        connector ACL. This mirrors the real enforcement bypass; a detector
        driven by acl_effect='deny' rows would not, since the policy engine
        never consults deny-effect ACL rows (only 'allow' rows build
        connector_allowed_user_ids — see resource_context_builder.py).
        """
        allow_rows = (
            await db.execute(
                select(SourceAclMapping.connector_connection_id, SourceAclMapping.user_id).where(
                    SourceAclMapping.organization_id == organization_id,
                    SourceAclMapping.acl_effect == "allow",
                    SourceAclMapping.principal_type == "user",
                    SourceAclMapping.is_active.is_(True),
                )
            )
        ).all()
        if not allow_rows:
            return
        allowed_by_connection: dict[UUID, set[str]] = {}
        for connection_id, user_id in allow_rows:
            if connection_id is None or user_id is None:
                continue
            allowed_by_connection.setdefault(connection_id, set()).add(str(user_id))
        if not allowed_by_connection:
            return

        doc_rows = (
            await db.execute(
                select(Document.id, ExternalItem.connection_id)
                .join(ExternalItem, ExternalItem.id == Document.connector_external_item_id)
                .where(
                    Document.organization_id == organization_id,
                    ExternalItem.connection_id.in_(list(allowed_by_connection.keys())),
                )
            )
        ).all()
        if not doc_rows:
            return
        doc_to_connection: dict[UUID, UUID] = {doc_id: conn_id for doc_id, conn_id in doc_rows}

        collections_by_doc = await batch_get_collection_ids_for_documents(
            db, document_ids=list(doc_to_connection.keys())
        )
        all_collection_ids = {UUID(cid) for ids in collections_by_doc.values() for cid in ids}
        if not all_collection_ids:
            return

        collections = (
            (
                await db.execute(
                    select(Collection).where(
                        Collection.id.in_(all_collection_ids),
                        Collection.organization_id == organization_id,
                        Collection.is_archived.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        collections_by_id = {c.id: c for c in collections}
        if not collections_by_id:
            return

        role_grants: dict[UUID, set[str]] = {}
        member_grants: dict[UUID, set[str]] = {}
        restricted_collection_ids = [
            c.id for c in collections if c.access_policy in ("selected_roles", "selected_members")
        ]
        if restricted_collection_ids:
            grant_rows = (
                await db.execute(
                    select(
                        CollectionAccessGrant.collection_id,
                        CollectionAccessGrant.grantee_type,
                        CollectionAccessGrant.grantee_value,
                    ).where(CollectionAccessGrant.collection_id.in_(restricted_collection_ids))
                )
            ).all()
            for collection_id, grantee_type, grantee_value in grant_rows:
                if grantee_type == "role":
                    role_grants.setdefault(collection_id, set()).add(grantee_value)
                elif grantee_type == "member":
                    member_grants.setdefault(collection_id, set()).add(grantee_value)

        members = (
            await db.execute(
                select(OrganizationMember.user_id, OrganizationMember.role).where(
                    OrganizationMember.organization_id == organization_id,
                )
            )
        ).all()
        if not members:
            return
        roles_with_collection_access = {
            role
            for role, perms in ROLE_PERMISSIONS.items()
            if PermissionType.chat_use_collections in perms
        }
        members_by_role: dict[str, list[UUID]] = {}
        for user_id, role in members:
            members_by_role.setdefault(role, []).append(user_id)

        seen: set[tuple[UUID, UUID]] = set()
        for doc_id, connection_id in doc_to_connection.items():
            allowed_users = allowed_by_connection.get(connection_id, set())
            for collection_id_str in collections_by_doc.get(str(doc_id), []):
                collection = collections_by_id.get(UUID(collection_id_str))
                if collection is None:
                    continue

                reachable: list[tuple[UUID, str]]
                if collection.access_policy == "org_wide":
                    reachable = [
                        (user_id, role)
                        for user_id, role in members
                        if role in roles_with_collection_access
                    ]
                elif collection.access_policy == "selected_roles":
                    reachable = [
                        (user_id, role)
                        for role in role_grants.get(collection.id, set())
                        if role in roles_with_collection_access
                        for user_id in members_by_role.get(role, [])
                    ]
                elif collection.access_policy == "selected_members":
                    granted_member_ids = member_grants.get(collection.id, set())
                    reachable = [
                        (user_id, role)
                        for user_id, role in members
                        if str(user_id) in granted_member_ids
                        and role in roles_with_collection_access
                    ]
                else:
                    # admin_only: rule 8 would not grant a non-admin here.
                    reachable = []

                for user_id, role in reachable:
                    if role in _ADMIN_ROLE_NAMES or str(user_id) in allowed_users:
                        continue
                    dedupe_key = (user_id, doc_id)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    stats.conflicts_detected += 1
                    created = await self._upsert_conflict(
                        db,
                        organization_id=organization_id,
                        subject_type="user",
                        subject_value=str(user_id),
                        user_id=user_id,
                        role_name=role,
                        resource_type="document",
                        resource_id=str(doc_id),
                        action="read_only",
                        conflict_type="collection_allow_connector_acl_deny",
                        severity_db="high",
                        summary=(
                            f"User {user_id} reaches document {doc_id} via collection "
                            f"{collection.id} (access_policy={collection.access_policy}), "
                            f"bypassing connector {connection_id}'s ACL allow-list."
                        ),
                        context={
                            "collection_id": str(collection.id),
                            "connector_connection_id": str(connection_id),
                            "access_policy": collection.access_policy,
                        },
                    )
                    if created:
                        stats.conflicts_created += 1

    async def _detect_citation_visible_source_hidden(
        self,
        db: AsyncSession,
        organization_id: UUID,
        stats: _ScanStats,
    ) -> None:
        """A citation remains visible in a chat transcript, but the document it
        cites would now be denied to the citing user: either the backing
        connector connection has been revoked, or an explicit
        ResourceAccessDeny for that (document, user) pair exists.

        Reproduces the dominant real case of documents.py's citation-preview
        "revoked" trust check without duplicating that service's full
        multi-table trust computation.
        """
        rows = (
            await db.execute(
                select(Citation.id, Citation.document_id, ChatSession.user_id)
                .join(ChatMessage, ChatMessage.id == Citation.chat_message_id)
                .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
                .where(ChatSession.organization_id == organization_id)
            )
        ).all()
        if not rows:
            return

        doc_ids = {doc_id for _, doc_id, _ in rows}
        documents = (
            (
                await db.execute(
                    select(Document).where(
                        Document.id.in_(doc_ids),
                        Document.organization_id == organization_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_document_ids = {d.id for d in documents}

        ext_item_ids = [
            d.connector_external_item_id
            for d in documents
            if d.connector_external_item_id is not None
        ]
        revoked_document_ids: set[UUID] = set()
        if ext_item_ids:
            ext_to_conn = await batch_get_connection_ids_for_external_items(
                db, external_item_ids=ext_item_ids
            )
            connection_ids = {UUID(cid) for cid in ext_to_conn.values()}
            if connection_ids:
                revoked_connections = set(
                    (
                        await db.execute(
                            select(ConnectorConnection.id).where(
                                ConnectorConnection.id.in_(connection_ids),
                                ConnectorConnection.status == "revoked",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for doc in documents:
                    if doc.connector_external_item_id is None:
                        continue
                    conn_id_str = ext_to_conn.get(str(doc.connector_external_item_id))
                    if conn_id_str and UUID(conn_id_str) in revoked_connections:
                        revoked_document_ids.add(doc.id)

        denies_by_doc = await batch_get_explicit_denies(
            db,
            organization_id=organization_id,
            resource_type=ResourceType.document,
            resource_ids=[str(d) for d in doc_ids],
        )

        for citation_id, document_id, citing_user_id in rows:
            if document_id not in existing_document_ids or citing_user_id is None:
                continue
            reason: str | None = None
            if document_id in revoked_document_ids:
                reason = "connector_revoked"
            elif str(citing_user_id) in denies_by_doc.get(str(document_id), []):
                reason = "explicit_deny"
            if reason is None:
                continue
            stats.conflicts_detected += 1
            created = await self._upsert_conflict(
                db,
                organization_id=organization_id,
                subject_type="user",
                subject_value=str(citing_user_id),
                user_id=citing_user_id,
                role_name=None,
                resource_type="citation",
                resource_id=str(citation_id),
                action="cite",
                conflict_type="citation_visible_source_hidden",
                severity_db="critical",
                summary=(
                    f"Citation {citation_id} remains visible to user {citing_user_id} "
                    f"but its source document {document_id} is no longer accessible "
                    f"to them ({reason})."
                ),
                context={"document_id": str(document_id), "reason": reason},
            )
            if created:
                stats.conflicts_created += 1

    async def _detect_graph_entity_visible_evidence_inaccessible(
        self,
        db: AsyncSession,
        organization_id: UUID,
        stats: _ScanStats,
    ) -> None:
        """Structural conflict: PolicyEngine does not gate graph_entity by
        collection (visible org-wide to anyone with graph_view), while
        graph_evidence is collection-gated. A restricted collection's documents
        can therefore back entities visible to users who could never see the
        underlying evidence.

        Bounded to documents in restricted (non-org-wide) collections — never
        crawls the full graph corpus. Uses subject_type='collection' since the
        conflict is structural, not tied to one principal (AuthorizationConflict
        places no CHECK constraint on subject_type, unlike the grant/deny models).
        """
        restricted_collections = (
            await db.execute(
                select(Collection.id, Collection.access_policy).where(
                    Collection.organization_id == organization_id,
                    Collection.access_policy != "org_wide",
                    Collection.is_archived.is_(False),
                )
            )
        ).all()
        if not restricted_collections:
            return
        policy_by_collection: dict[UUID, str] = {
            collection_id: policy for collection_id, policy in restricted_collections
        }

        doc_rows = (
            await db.execute(
                select(CollectionDocument.collection_id, CollectionDocument.document_id).where(
                    CollectionDocument.collection_id.in_(list(policy_by_collection.keys()))
                )
            )
        ).all()
        if not doc_rows:
            return

        doc_ids_by_collection: dict[UUID, list[UUID]] = {}
        for collection_id, document_id in doc_rows:
            doc_ids_by_collection.setdefault(collection_id, []).append(document_id)
        all_doc_id_strings = list({str(document_id) for _, document_id in doc_rows})

        entities_by_document = await _evidence_repo.list_entities_for_documents(
            organization_id=organization_id, document_ids=all_doc_id_strings
        )
        if not entities_by_document:
            return

        seen: set[tuple[UUID, str]] = set()
        for collection_id, document_ids in doc_ids_by_collection.items():
            for document_id in document_ids:
                for entity_id in entities_by_document.get(str(document_id), []):
                    dedupe_key = (collection_id, entity_id)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    stats.conflicts_detected += 1
                    created = await self._upsert_conflict(
                        db,
                        organization_id=organization_id,
                        subject_type="collection",
                        subject_value=str(collection_id),
                        user_id=None,
                        role_name=None,
                        resource_type="graph_entity",
                        resource_id=entity_id,
                        action="read_only",
                        conflict_type="graph_entity_visible_evidence_inaccessible",
                        severity_db="medium",
                        summary=(
                            f"Graph entity {entity_id} is visible org-wide to anyone with "
                            f"graph_view, but its evidence is sourced from a document in "
                            f"restricted collection {collection_id} "
                            f"(access_policy={policy_by_collection.get(collection_id)})."
                        ),
                        context={
                            "collection_id": str(collection_id),
                            "collection_access_policy": policy_by_collection.get(collection_id),
                        },
                    )
                    if created:
                        stats.conflicts_created += 1

    async def _upsert_conflict(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        subject_type: str,
        subject_value: str,
        user_id: UUID | None,
        role_name: str | None,
        resource_type: str,
        resource_id: str | None,
        action: str,
        conflict_type: str,
        severity_db: str,
        summary: str,
        grant_id: UUID | None = None,
        deny_id: UUID | None = None,
        context: dict | None = None,
    ) -> bool:
        """Create the conflict if no open/investigating instance already exists. Returns True if created."""
        existing = await _repo.find_existing_open_conflict(
            db,
            organization_id=organization_id,
            subject_value=subject_value,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            conflict_type=conflict_type,
        )
        if existing:
            return False
        await _repo.create_conflict(
            db,
            organization_id=organization_id,
            subject_type=subject_type,
            subject_value=subject_value,
            user_id=user_id,
            role_name=role_name,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            conflict_type=conflict_type,
            severity_db=severity_db,
            conflict_summary=summary,
            grant_id=grant_id,
            deny_id=deny_id,
            context=context,
        )
        return True


def _is_valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(value)
        return True
    except ValueError:
        return False
