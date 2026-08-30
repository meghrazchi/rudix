"""Aggregation service for the F354 Permission and Access Report.

Rolls up existing grant/deny/connector-ACL/conflict/audit-log signals into a
summary, charts, and a paginated per-row access table. No new persisted state
is introduced — every field read here already exists from prior features
(F330 policy engine, F335 conflict detection, F170 connector sync conflicts,
F245 connector permission review, F161 domain verification).

Follows the fetch-then-aggregate-in-Python style established by
`app/domains/admin/services/usage_adoption_service.py` (F353), including its
date-range helpers, to avoid the SQLite-vs-Postgres traps that service's own
history flagged: no `func.distinct()` on UUID columns (dedupe in Python on
`str(uuid)` keys instead) and no `func.now()` (bind a Python-computed
`datetime.now(UTC)` as a literal instead).

The access-row table deliberately never enumerates the full user × resource
matrix (unbounded). Rows come only from real, bounded tables: active
resource grants, active resource denies, active connector-ACL allow mappings,
and open/investigating conflicts (merged onto an existing row when the
subject/resource pair matches, otherwise standalone). "Inherited" access is
surfaced as a bounded aggregate in `access_distribution`, not as enumerated
per-user rows — see `_access_distribution()`.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.audit_events import AUTHZ_ACCESS_DENIED
from app.domains.permissions.schemas.permissions_access_report import (
    AccessSourceCountRow,
    BroadAccessUserRow,
    FailedAccessAttemptPoint,
    PermissionsAccessChartsResponse,
    PermissionsAccessRowListResponse,
    PermissionsAccessRowResponse,
    PermissionsAccessSummaryResponse,
    ResourceTypeCountRow,
    RoleCountRow,
)
from app.models.authorization import (
    AuthorizationConflict,
    ResourceAccessDeny,
    ResourceAccessGrant,
    SourceAclMapping,
)
from app.models.collection import Collection, CollectionDocument
from app.models.connector import ConnectorConnection, ConnectorPermissionReview
from app.models.connector_sync import SyncConflict
from app.models.document import Document
from app.models.org_domain_verification import OrgDomainVerification
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User

_ADMIN_ROLE_NAMES = frozenset({"owner", "admin"})
_OPEN_CONFLICT_STATUSES = ("open", "investigating")
_ACL_MISMATCH_TYPES = ("acl_changed", "permission_revoked")
_DEFAULT_WINDOW_DAYS = 30


def _is_valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _resolve_range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    today = _now().date()
    resolved_to = to_date or today
    resolved_from = from_date or resolved_to - timedelta(days=_DEFAULT_WINDOW_DAYS - 1)
    if resolved_from > resolved_to:
        resolved_from, resolved_to = resolved_to, resolved_from
    return resolved_from, resolved_to


def _range_datetimes(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(from_date, time.min, tzinfo=UTC),
        datetime.combine(to_date, time.max, tzinfo=UTC),
    )


@dataclass
class PermissionsAccessFilters:
    role: str | None = None
    access_source: str | None = None
    resource_type: str | None = None
    conflict_status: str | None = None
    search: str | None = None


class PermissionsAccessReportService:
    async def get_summary(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> PermissionsAccessSummaryResponse:
        from_dt, to_dt = _range_datetimes(*_resolve_range(from_date, to_date))

        members = await self._members(session, organization_id=organization_id)
        total_users = len(members)
        admin_users = sum(1 for _, role in members.items() if role in _ADMIN_ROLE_NAMES)

        external_users, external_is_heuristic = await self._count_external_users(
            session, organization_id=organization_id, members=members
        )

        non_admin_ids = {uid for uid, role in members.items() if role not in _ADMIN_ROLE_NAMES}
        broad_access_reasons = await self._broad_access_user_reasons(
            session, organization_id=organization_id, non_admin_ids=non_admin_ids
        )

        conflicts_open = (
            await session.execute(
                select(func.count())
                .select_from(AuthorizationConflict)
                .where(
                    AuthorizationConflict.organization_id == organization_id,
                    AuthorizationConflict.status.in_(_OPEN_CONFLICT_STATUSES),
                )
            )
        ).scalar_one()

        orphaned_grants = await self._count_orphaned_grants(
            session, organization_id=organization_id
        )

        now = _now()
        expired_active_grants = (
            await session.execute(
                select(func.count())
                .select_from(ResourceAccessGrant)
                .where(
                    ResourceAccessGrant.organization_id == organization_id,
                    ResourceAccessGrant.status == "active",
                    ResourceAccessGrant.expires_at.is_not(None),
                    ResourceAccessGrant.expires_at < now,
                )
            )
        ).scalar_one()

        connector_acl_mismatches = (
            await session.execute(
                select(func.count())
                .select_from(SyncConflict)
                .where(
                    SyncConflict.organization_id == organization_id,
                    SyncConflict.conflict_type.in_(_ACL_MISMATCH_TYPES),
                    SyncConflict.status == "open",
                )
            )
        ).scalar_one()

        resources_without_owner = await self._count_resources_without_owner(
            session, organization_id=organization_id
        )

        unauthorized_access_attempts = (
            await session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.organization_id == organization_id,
                    AuditLog.action == AUTHZ_ACCESS_DENIED,
                    AuditLog.created_at >= from_dt,
                    AuditLog.created_at <= to_dt,
                )
            )
        ).scalar_one()

        return PermissionsAccessSummaryResponse(
            total_users=total_users,
            admin_users=admin_users,
            external_users=external_users,
            external_users_is_heuristic=external_is_heuristic,
            broad_access_users=len(broad_access_reasons),
            permission_conflicts_open=int(conflicts_open),
            orphaned_grants=orphaned_grants,
            expired_active_grants=int(expired_active_grants),
            connector_acl_mismatches=int(connector_acl_mismatches),
            resources_without_owner=resources_without_owner,
            unauthorized_access_attempts=int(unauthorized_access_attempts),
            generated_at=now,
        )

    async def get_charts(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> PermissionsAccessChartsResponse:
        from_dt, to_dt = _range_datetimes(*_resolve_range(from_date, to_date))

        members = await self._members(session, organization_id=organization_id)
        role_counts: dict[str, int] = {}
        for role in members.values():
            role_counts[role] = role_counts.get(role, 0) + 1
        users_by_role = [RoleCountRow(role=r, count=c) for r, c in sorted(role_counts.items())]

        access_distribution = await self._access_distribution(
            session, organization_id=organization_id
        )

        conflict_rows = (
            await session.execute(
                select(AuthorizationConflict.resource_type, func.count())
                .where(
                    AuthorizationConflict.organization_id == organization_id,
                    AuthorizationConflict.status.in_(_OPEN_CONFLICT_STATUSES),
                )
                .group_by(AuthorizationConflict.resource_type)
            )
        ).all()
        conflicts_by_resource_type = [
            ResourceTypeCountRow(resource_type=rt, count=int(c)) for rt, c in conflict_rows
        ]

        broad_access_rows = await self._broad_access_user_rows(
            session, organization_id=organization_id, members=members
        )

        failed_access_attempts = await self._failed_access_attempts_series(
            session, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
        )

        return PermissionsAccessChartsResponse(
            users_by_role=users_by_role,
            access_distribution=access_distribution,
            conflicts_by_resource_type=conflicts_by_resource_type,
            broad_access_users=broad_access_rows,
            failed_access_attempts=failed_access_attempts,
            generated_at=_now(),
        )

    async def list_rows(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: PermissionsAccessFilters,
        page: int = 1,
        page_size: int = 25,
    ) -> PermissionsAccessRowListResponse:
        rows = await self._build_rows(session, organization_id=organization_id, filters=filters)
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        return PermissionsAccessRowListResponse(
            items=page_rows, total=total, page=page, page_size=page_size
        )

    async def build_export_csv(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: PermissionsAccessFilters,
    ) -> str:
        rows = await self._build_rows(session, organization_id=organization_id, filters=filters)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        # Structural metadata only — never resource content or citation text
        # (F354 acceptance criterion: "no unauthorized source content is shown").
        writer.writerow(
            [
                "user_name",
                "user_email",
                "role",
                "team",
                "resource_type",
                "resource_label",
                "access_level",
                "access_source",
                "conflict_status",
                "last_access",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.user_name or "",
                    row.user_email or "",
                    row.role or "",
                    row.team or "",
                    row.resource_type,
                    row.resource_label or "",
                    row.access_level,
                    row.access_source,
                    row.conflict_status or "",
                    row.last_access.isoformat() if row.last_access else "",
                ]
            )
        return buffer.getvalue()

    # -- internal: shared lookups ----------------------------------------------

    async def _members(self, session: AsyncSession, *, organization_id: UUID) -> dict[UUID, str]:
        rows = (
            await session.execute(
                select(OrganizationMember.user_id, OrganizationMember.role).where(
                    OrganizationMember.organization_id == organization_id
                )
            )
        ).all()
        return {user_id: role for user_id, role in rows}

    async def _user_info(
        self, session: AsyncSession, *, user_ids: set[UUID]
    ) -> dict[UUID, tuple[str, str | None]]:
        if not user_ids:
            return {}
        rows = (
            await session.execute(
                select(User.id, User.email, User.display_name).where(User.id.in_(user_ids))
            )
        ).all()
        return {user_id: (email, display_name) for user_id, email, display_name in rows}

    async def _count_external_users(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        members: dict[UUID, str],
    ) -> tuple[int, bool]:
        if not members:
            return 0, False
        user_info = await self._user_info(session, user_ids=set(members.keys()))
        emails = [email for email, _ in user_info.values() if email]

        verified_domains = set(
            (
                await session.execute(
                    select(OrgDomainVerification.domain).where(
                        OrgDomainVerification.organization_id == organization_id,
                        OrgDomainVerification.status == "verified",
                    )
                )
            )
            .scalars()
            .all()
        )

        is_heuristic = not verified_domains
        if is_heuristic:
            domain_counts: dict[str, int] = {}
            for email in emails:
                domain = _email_domain(email)
                if domain:
                    domain_counts[domain] = domain_counts.get(domain, 0) + 1
            internal_domains = (
                {max(domain_counts, key=lambda d: domain_counts[d])} if domain_counts else set()
            )
        else:
            internal_domains = verified_domains

        external_count = sum(
            1
            for email in emails
            if _email_domain(email) and _email_domain(email) not in internal_domains
        )
        return external_count, is_heuristic

    async def _broad_access_user_reasons(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        non_admin_ids: set[UUID],
    ) -> dict[UUID, str]:
        if not non_admin_ids:
            return {}
        reasons: dict[UUID, str] = {}

        wildcard_users = (
            (
                await session.execute(
                    select(ResourceAccessGrant.user_id).where(
                        ResourceAccessGrant.organization_id == organization_id,
                        ResourceAccessGrant.status == "active",
                        ResourceAccessGrant.principal_type == "user",
                        ResourceAccessGrant.resource_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in wildcard_users:
            if user_id in non_admin_ids:
                reasons.setdefault(user_id, "Holds a grant scoped to an entire resource type")

        broad_scope_connections = (
            (
                await session.execute(
                    select(ConnectorPermissionReview.connection_id).where(
                        ConnectorPermissionReview.organization_id == organization_id,
                        ConnectorPermissionReview.is_broad_scope.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if broad_scope_connections:
            acl_users = (
                (
                    await session.execute(
                        select(SourceAclMapping.user_id).where(
                            SourceAclMapping.organization_id == organization_id,
                            SourceAclMapping.connector_connection_id.in_(broad_scope_connections),
                            SourceAclMapping.acl_effect == "allow",
                            SourceAclMapping.is_active.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for user_id in acl_users:
                if user_id in non_admin_ids:
                    reasons.setdefault(
                        user_id, "Allow-listed on a connector flagged as broad-scope"
                    )

        return reasons

    async def _broad_access_user_rows(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        members: dict[UUID, str],
    ) -> list[BroadAccessUserRow]:
        non_admin_ids = {uid for uid, role in members.items() if role not in _ADMIN_ROLE_NAMES}
        reasons = await self._broad_access_user_reasons(
            session, organization_id=organization_id, non_admin_ids=non_admin_ids
        )
        if not reasons:
            return []
        user_info = await self._user_info(session, user_ids=set(reasons.keys()))
        rows: list[BroadAccessUserRow] = []
        for user_id, reason in reasons.items():
            email, display_name = user_info.get(user_id, ("", None))
            rows.append(
                BroadAccessUserRow(
                    user_id=str(user_id),
                    name=display_name or email,
                    email=email,
                    role=members.get(user_id, ""),
                    reason=reason,
                )
            )
        return rows

    async def _count_orphaned_grants(self, session: AsyncSession, *, organization_id: UUID) -> int:
        grants = (
            await session.execute(
                select(ResourceAccessGrant.resource_type, ResourceAccessGrant.resource_id).where(
                    ResourceAccessGrant.organization_id == organization_id,
                    ResourceAccessGrant.status == "active",
                    ResourceAccessGrant.resource_id.is_not(None),
                )
            )
        ).all()
        if not grants:
            return 0

        doc_ids_referenced = {
            resource_id
            for resource_type, resource_id in grants
            if resource_type == "document" and _is_valid_uuid(resource_id)
        }
        existing_doc_ids: set[str] = set()
        if doc_ids_referenced:
            rows = (
                (
                    await session.execute(
                        select(Document.id).where(
                            Document.id.in_({UUID(d) for d in doc_ids_referenced}),
                            Document.organization_id == organization_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_doc_ids = {str(r) for r in rows}

        conn_ids_referenced = {
            resource_id
            for resource_type, resource_id in grants
            if resource_type == "connector" and _is_valid_uuid(resource_id)
        }
        existing_conn_ids: set[str] = set()
        if conn_ids_referenced:
            rows = (
                (
                    await session.execute(
                        select(ConnectorConnection.id).where(
                            ConnectorConnection.id.in_({UUID(c) for c in conn_ids_referenced}),
                            ConnectorConnection.organization_id == organization_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_conn_ids = {str(r) for r in rows}

        orphaned = 0
        for resource_type, resource_id in grants:
            if resource_type == "document":
                if not _is_valid_uuid(resource_id) or resource_id not in existing_doc_ids:
                    orphaned += 1
            elif resource_type == "connector":
                if not _is_valid_uuid(resource_id) or resource_id not in existing_conn_ids:
                    orphaned += 1
        return orphaned

    async def _count_resources_without_owner(
        self, session: AsyncSession, *, organization_id: UUID
    ) -> int:
        doc_count = (
            await session.execute(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.organization_id == organization_id,
                    Document.uploaded_by_user_id.is_(None),
                )
            )
        ).scalar_one()
        collection_count = (
            await session.execute(
                select(func.count())
                .select_from(Collection)
                .where(
                    Collection.organization_id == organization_id,
                    Collection.owner_id.is_(None),
                )
            )
        ).scalar_one()
        return int(doc_count) + int(collection_count)

    async def _access_distribution(
        self, session: AsyncSession, *, organization_id: UUID
    ) -> list[AccessSourceCountRow]:
        explicit_grant_count = (
            await session.execute(
                select(func.count())
                .select_from(ResourceAccessGrant)
                .where(
                    ResourceAccessGrant.organization_id == organization_id,
                    ResourceAccessGrant.status == "active",
                )
            )
        ).scalar_one()
        connector_acl_count = (
            await session.execute(
                select(func.count())
                .select_from(SourceAclMapping)
                .where(
                    SourceAclMapping.organization_id == organization_id,
                    SourceAclMapping.acl_effect == "allow",
                    SourceAclMapping.is_active.is_(True),
                )
            )
        ).scalar_one()

        # Bounded resource-centric aggregate for "inherited" access posture —
        # never enumerates which user reaches which document via which
        # collection (that's the unbounded matrix this report avoids).
        collection_doc_rows = (
            await session.execute(
                select(Collection.access_policy, CollectionDocument.document_id)
                .join(CollectionDocument, CollectionDocument.collection_id == Collection.id)
                .where(
                    Collection.organization_id == organization_id,
                    Collection.is_archived.is_(False),
                )
            )
        ).all()
        docs_by_policy: dict[str, set] = {}
        for policy, doc_id in collection_doc_rows:
            docs_by_policy.setdefault(policy, set()).add(doc_id)

        return [
            AccessSourceCountRow(access_source="explicit_grant", count=int(explicit_grant_count)),
            AccessSourceCountRow(access_source="connector_acl", count=int(connector_acl_count)),
            AccessSourceCountRow(
                access_source="inherited_org_wide", count=len(docs_by_policy.get("org_wide", set()))
            ),
            AccessSourceCountRow(
                access_source="inherited_restricted",
                count=sum(len(v) for k, v in docs_by_policy.items() if k != "org_wide"),
            ),
        ]

    async def _failed_access_attempts_series(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[FailedAccessAttemptPoint]:
        rows = (
            (
                await session.execute(
                    select(AuditLog.created_at).where(
                        AuditLog.organization_id == organization_id,
                        AuditLog.action == AUTHZ_ACCESS_DENIED,
                        AuditLog.created_at >= from_dt,
                        AuditLog.created_at <= to_dt,
                    )
                )
            )
            .scalars()
            .all()
        )
        counts: dict[str, int] = {}
        for created_at in rows:
            day = created_at.date().isoformat()
            counts[day] = counts.get(day, 0) + 1
        return [
            FailedAccessAttemptPoint(date=day, count=count) for day, count in sorted(counts.items())
        ]

    # -- internal: access-row table ---------------------------------------------

    async def _build_rows(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        filters: PermissionsAccessFilters,
    ) -> list[PermissionsAccessRowResponse]:
        members = await self._members(session, organization_id=organization_id)
        user_info = await self._user_info(session, user_ids=set(members.keys()))

        rows: dict[tuple[str, str, str, str], PermissionsAccessRowResponse] = {}

        def _key(
            subject_type: str, subject_value: str, resource_type: str, resource_id: str | None
        ) -> tuple[str, str, str, str]:
            return (subject_type, subject_value, resource_type, resource_id or "")

        def _user_fields(user_id: UUID | None) -> tuple[str | None, str | None, str | None]:
            if user_id is None:
                return None, None, None
            email, display_name = user_info.get(user_id, (None, None))
            return str(user_id), (display_name or email), email

        grants = (
            (
                await session.execute(
                    select(ResourceAccessGrant).where(
                        ResourceAccessGrant.organization_id == organization_id,
                        ResourceAccessGrant.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        for grant in grants:
            user_id_str, user_name, user_email = _user_fields(grant.user_id)
            key = _key(
                grant.principal_type, grant.principal_value, grant.resource_type, grant.resource_id
            )
            rows[key] = PermissionsAccessRowResponse(
                id=str(grant.id),
                user_id=user_id_str,
                user_name=user_name,
                user_email=user_email,
                role=members.get(grant.user_id) if grant.user_id else grant.role_name,
                team=grant.principal_value if grant.principal_type == "team" else None,
                resource_id=grant.resource_id,
                resource_type=grant.resource_type,
                resource_label=None,
                access_level=grant.action,
                access_source="explicit_grant",
                conflict_status=None,
                last_access=None,
                grant_id=str(grant.id),
                conflict_id=None,
            )

        denies = (
            (
                await session.execute(
                    select(ResourceAccessDeny).where(
                        ResourceAccessDeny.organization_id == organization_id,
                        ResourceAccessDeny.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        for deny in denies:
            user_id_str, user_name, user_email = _user_fields(deny.user_id)
            key = _key(
                deny.principal_type, deny.principal_value, deny.resource_type, deny.resource_id
            )
            rows[key] = PermissionsAccessRowResponse(
                id=str(deny.id),
                user_id=user_id_str,
                user_name=user_name,
                user_email=user_email,
                role=members.get(deny.user_id) if deny.user_id else deny.role_name,
                team=deny.principal_value if deny.principal_type == "team" else None,
                resource_id=deny.resource_id,
                resource_type=deny.resource_type,
                resource_label=None,
                access_level="denied",
                access_source="explicit_deny",
                conflict_status=None,
                last_access=None,
                grant_id=None,
                conflict_id=None,
            )

        acls = (
            (
                await session.execute(
                    select(SourceAclMapping).where(
                        SourceAclMapping.organization_id == organization_id,
                        SourceAclMapping.acl_effect == "allow",
                        SourceAclMapping.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        for acl in acls:
            key = _key(acl.principal_type, acl.principal_value, acl.source_type, acl.source_id)
            if key in rows:
                # An explicit grant/deny already governs this pair (rule 6/7
                # precede rule 9) — don't override with the weaker ACL source.
                continue
            user_id_str, user_name, user_email = _user_fields(acl.user_id)
            rows[key] = PermissionsAccessRowResponse(
                id=str(acl.id),
                user_id=user_id_str,
                user_name=user_name,
                user_email=user_email,
                role=members.get(acl.user_id) if acl.user_id else None,
                team=acl.principal_value if acl.principal_type == "team" else None,
                resource_id=acl.source_id,
                resource_type=acl.source_type,
                resource_label=None,
                access_level=acl.action,
                access_source="connector_acl",
                conflict_status=None,
                last_access=None,
                grant_id=None,
                conflict_id=None,
            )

        conflicts = (
            (
                await session.execute(
                    select(AuthorizationConflict).where(
                        AuthorizationConflict.organization_id == organization_id,
                        AuthorizationConflict.status.in_(_OPEN_CONFLICT_STATUSES),
                    )
                )
            )
            .scalars()
            .all()
        )
        for conflict in conflicts:
            key = _key(
                conflict.subject_type,
                conflict.subject_value,
                conflict.resource_type,
                conflict.resource_id,
            )
            existing = rows.get(key)
            if existing is not None:
                existing.conflict_status = conflict.status
                existing.conflict_id = str(conflict.id)
                continue
            user_id_str, user_name, user_email = _user_fields(conflict.user_id)
            rows[key] = PermissionsAccessRowResponse(
                id=str(conflict.id),
                user_id=user_id_str,
                user_name=user_name,
                user_email=user_email,
                role=members.get(conflict.user_id) if conflict.user_id else conflict.role_name,
                team=conflict.subject_value if conflict.subject_type == "team" else None,
                resource_id=conflict.resource_id,
                resource_type=conflict.resource_type,
                resource_label=None,
                access_level="conflict",
                access_source="conflict",
                conflict_status=conflict.status,
                last_access=None,
                grant_id=str(conflict.grant_id) if conflict.grant_id else None,
                conflict_id=str(conflict.id),
            )

        result = list(rows.values())
        await self._resolve_resource_labels(session, organization_id=organization_id, rows=result)
        result = self._apply_filters(result, filters)
        result.sort(key=lambda r: (r.resource_type, r.resource_id or "", r.user_id or ""))
        return result

    async def _resolve_resource_labels(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        rows: list[PermissionsAccessRowResponse],
    ) -> None:
        doc_ids = {
            r.resource_id
            for r in rows
            if r.resource_type == "document" and _is_valid_uuid(r.resource_id)
        }
        if doc_ids:
            docs = (
                await session.execute(
                    select(Document.id, Document.filename).where(
                        Document.id.in_({UUID(d) for d in doc_ids}),
                        Document.organization_id == organization_id,
                    )
                )
            ).all()
            doc_labels = {str(doc_id): filename for doc_id, filename in docs}
            for r in rows:
                if r.resource_type == "document" and r.resource_id in doc_labels:
                    r.resource_label = doc_labels[r.resource_id]

        collection_ids = {
            r.resource_id
            for r in rows
            if r.resource_type == "collection" and _is_valid_uuid(r.resource_id)
        }
        if collection_ids:
            collections = (
                await session.execute(
                    select(Collection.id, Collection.name).where(
                        Collection.id.in_({UUID(c) for c in collection_ids}),
                        Collection.organization_id == organization_id,
                    )
                )
            ).all()
            collection_labels = {str(cid): name for cid, name in collections}
            for r in rows:
                if r.resource_type == "collection" and r.resource_id in collection_labels:
                    r.resource_label = collection_labels[r.resource_id]

        connector_ids = {
            r.resource_id
            for r in rows
            if r.resource_type == "connector" and _is_valid_uuid(r.resource_id)
        }
        if connector_ids:
            connections = (
                await session.execute(
                    select(ConnectorConnection.id, ConnectorConnection.display_name).where(
                        ConnectorConnection.id.in_({UUID(c) for c in connector_ids}),
                        ConnectorConnection.organization_id == organization_id,
                    )
                )
            ).all()
            connection_labels = {str(cid): name for cid, name in connections}
            for r in rows:
                if r.resource_type == "connector" and r.resource_id in connection_labels:
                    r.resource_label = connection_labels[r.resource_id]

    def _apply_filters(
        self,
        rows: list[PermissionsAccessRowResponse],
        filters: PermissionsAccessFilters,
    ) -> list[PermissionsAccessRowResponse]:
        def matches(row: PermissionsAccessRowResponse) -> bool:
            if filters.role and row.role != filters.role:
                return False
            if filters.access_source and row.access_source != filters.access_source:
                return False
            if filters.resource_type and row.resource_type != filters.resource_type:
                return False
            if filters.conflict_status and row.conflict_status != filters.conflict_status:
                return False
            if filters.search:
                needle = filters.search.lower()
                haystack = " ".join(
                    part
                    for part in [row.user_name, row.user_email, row.resource_id, row.resource_label]
                    if part
                ).lower()
                if needle not in haystack:
                    return False
            return True

        return [r for r in rows if matches(r)]


def _email_domain(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].lower()
