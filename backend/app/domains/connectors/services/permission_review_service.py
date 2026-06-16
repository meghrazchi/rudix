"""Connector permission review service for F169.

Analyses OAuth scopes and source configuration to surface broad-access
warnings, then tracks an explicit admin confirmation before the first sync.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.connector import ConnectorConnection, ConnectorPermissionReview

_logger = get_logger("connectors.permission_review")

# ---------------------------------------------------------------------------
# Scope-risk catalogue
# ---------------------------------------------------------------------------

# Known scopes that grant write or delete access — unexpected for read-only indexing.
_WRITE_SCOPES: frozenset[str] = frozenset(
    {
        "https://www.googleapis.com/auth/drive",  # full Drive (write)
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.appdata",
        "write:confluence-content",
        "write:jira-work",
        "write",
    }
)

# Scopes that grant admin-level access across an organisation.
_ADMIN_SCOPES: frozenset[str] = frozenset(
    {
        "https://www.googleapis.com/auth/admin.directory.user",
        "https://www.googleapis.com/auth/admin.directory.group",
        "admin:org:all",
        "admin:enterprise:all",
        "admin",
    }
)

# Scopes whose suffix/pattern signals broad org-wide read access.
_ORG_WIDE_SUFFIXES: tuple[str, ...] = (
    ".all",
    ":all",
    "_all",
)

# Provider-specific scope patterns that indicate org-wide access even without
# generic suffix markers.
_PROVIDER_ORG_WIDE: dict[str, frozenset[str]] = {
    "microsoft-sharepoint-onedrive": frozenset(
        {"Sites.Read.All", "Files.Read.All", "Sites.FullControl.All"}
    ),
    "google_drive": frozenset(
        {
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
        }
    ),
}


class ScopeWarning:
    """A single detected risk on a set of granted scopes."""

    def __init__(self, code: str, message: str, scope: str | None = None) -> None:
        self.code = code
        self.message = message
        self.scope = scope

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "scope": self.scope}


def analyze_scopes(
    scopes: list[str],
    *,
    provider_key: str,
    source_config: dict[str, Any] | None = None,
) -> tuple[list[ScopeWarning], bool]:
    """Return ``(warnings, is_broad_scope)`` for the given scope list.

    ``source_config`` is the connector's config dict (folder_ids, site_ids …)
    used to detect when a broad scope is unmitigated by any source filter.
    """
    warnings: list[ScopeWarning] = []
    is_broad = False

    normalised = {s.strip() for s in scopes if s.strip()}

    for scope in normalised:
        lower = scope.lower()

        if scope in _WRITE_SCOPES or "write" in lower or "delete" in lower:
            warnings.append(
                ScopeWarning(
                    code="write_permission",
                    message=(
                        f"Scope '{scope}' grants write or delete access. "
                        "Rudix only needs read-only scopes — verify this is intentional."
                    ),
                    scope=scope,
                )
            )
            is_broad = True
            continue

        if scope in _ADMIN_SCOPES or "admin" in lower:
            warnings.append(
                ScopeWarning(
                    code="admin_scope",
                    message=(
                        f"Scope '{scope}' grants admin-level access. "
                        "Admin scopes expose sensitive org data beyond what indexing requires."
                    ),
                    scope=scope,
                )
            )
            is_broad = True
            continue

        # Provider-specific org-wide markers
        provider_org_wide = _PROVIDER_ORG_WIDE.get(provider_key, frozenset())
        if scope in provider_org_wide:
            # Only flag as broad if no restricting source filter is configured
            config = source_config or {}
            has_filter = any(
                config.get(k)
                for k in (
                    "folder_ids",
                    "site_ids",
                    "drive_ids",
                    "space_keys",
                    "project_keys",
                    "page_ids",
                    "channel_ids",
                )
            )
            if not has_filter:
                warnings.append(
                    ScopeWarning(
                        code="org_wide_access",
                        message=(
                            f"Scope '{scope}' grants access to your entire organisation "
                            "with no source filter configured. Consider restricting to "
                            "specific folders, sites, or spaces."
                        ),
                        scope=scope,
                    )
                )
                is_broad = True
            continue

        # Generic suffix check
        if any(lower.endswith(sfx) for sfx in _ORG_WIDE_SUFFIXES):
            warnings.append(
                ScopeWarning(
                    code="broad_read",
                    message=(
                        f"Scope '{scope}' appears to grant broad read access "
                        "('*.all' pattern). Confirm this is the minimum required scope."
                    ),
                    scope=scope,
                )
            )
            is_broad = True

    return warnings, is_broad


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PermissionReviewNotFoundError(Exception):
    pass


class PermissionReviewService:
    """Create, retrieve, and confirm connector permission reviews."""

    async def get_or_create(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ConnectorPermissionReview:
        """Return the existing review or generate a fresh one from credential scopes."""
        existing = await self._get(
            db_session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        if existing is not None:
            return existing
        return await self._generate(
            db_session, organization_id=organization_id, connection_id=connection_id
        )

    async def confirm(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        user_id: UUID,
    ) -> ConnectorPermissionReview:
        """Confirm the permission review. Generates one from credential data if absent."""
        review = await self.get_or_create(
            db_session, organization_id=organization_id, connection_id=connection_id
        )
        review.is_confirmed = True
        review.reviewed_by_user_id = user_id
        review.reviewed_at = datetime.now(UTC)
        db_session.add(review)
        _logger.info(
            "permission_review_confirmed",
            connection_id=str(connection_id),
            user_id=str(user_id),
        )
        return review

    async def is_confirmed(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> bool:
        review = await self._get(
            db_session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        return review is not None and review.is_confirmed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ConnectorPermissionReview | None:
        result = await db_session.execute(
            select(ConnectorPermissionReview).where(
                ConnectorPermissionReview.organization_id == organization_id,
                ConnectorPermissionReview.connection_id == connection_id,
            )
        )
        return result.scalar_one_or_none()

    async def _generate(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ConnectorPermissionReview:
        """Build a permission review from the connection's live credential data."""
        conn_result = await db_session.execute(
            select(ConnectorConnection)
            .options(
                selectinload(ConnectorConnection.credentials),
                selectinload(ConnectorConnection.provider),
            )
            .where(
                ConnectorConnection.id == connection_id,
                ConnectorConnection.organization_id == organization_id,
            )
        )
        connection = conn_result.scalar_one_or_none()
        if connection is None:
            raise PermissionReviewNotFoundError(f"Connector connection {connection_id} not found")

        provider_key: str = connection.provider.key if connection.provider else ""
        auth_config: dict[str, Any] = dict(connection.auth_config_json or {})
        source_filters = {
            key: value
            for key, value in auth_config.items()
            if key != "provider_key" and value not in (None, "", [], {})
        }

        # Extract granted scopes from the active credential
        scopes: list[str] = []
        active_cred = next((c for c in (connection.credentials or []) if c.is_current), None)
        if active_cred and active_cred.scopes_json:
            scopes = list(active_cred.scopes_json)

        warnings, is_broad = analyze_scopes(
            scopes,
            provider_key=provider_key,
            source_config=auth_config,
        )

        snapshot: dict[str, Any] = {
            "provider_key": provider_key,
            "scopes_granted": scopes,
            "sync_direction": "read_only",
            "retention_policy": "indexed_until_connector_removed",
            "collection_id": (str(connection.collection_id) if connection.collection_id else None),
            "source_filters": source_filters,
            "analyzed_at": datetime.now(UTC).isoformat(),
        }

        review = ConnectorPermissionReview(
            organization_id=organization_id,
            connection_id=connection_id,
            permission_snapshot_json=snapshot,
            scope_warnings_json=[w.to_dict() for w in warnings],
            is_broad_scope=is_broad,
            is_confirmed=False,
        )
        db_session.add(review)
        await db_session.flush()
        return review
