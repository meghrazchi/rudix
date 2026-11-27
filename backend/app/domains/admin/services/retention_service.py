"""Per-table, per-organisation retention by batched delete (R04-09).

Five append-only tables can be trimmed: ``usage_events``, ``audit_logs``,
``authorization_decision_logs``, ``activity_timeline_events`` and ``webhook_deliveries``.
Each has a ``RETENTION_<TABLE>_DAYS`` setting; unset (the default) keeps every row. Audit logs
also honour an organisation override (``organization_governance_policies.audit_log_retention_days``):
the effective window is the override when set, else the platform default.

For each table with a window the service walks every organisation and deletes the oldest
rows older than ``now - window`` in batches of ``RETENTION_DELETE_BATCH_SIZE``, committing
after every batch so locks and WAL stay small. ``RETENTION_MAX_BATCHES_PER_RUN`` caps the
non-empty batches per table and run; the remainder is picked up by the next run. A rerun with
nothing to delete is a no-op. ``RETENTION_ENABLED=false`` stops every delete.

``now`` is injected so tests can freeze the clock.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.maintenance_metrics import record_retention_rows_deleted
from app.domains.admin.repositories.retention import RETENTION_TABLES, RetentionRepository

AUDIT_LOGS_TABLE = "audit_logs"

# Table -> settings attribute holding its platform retention window in days.
RETENTION_WINDOW_SETTINGS: dict[str, str] = {
    "usage_events": "retention_usage_events_days",
    AUDIT_LOGS_TABLE: "retention_audit_logs_days",
    "authorization_decision_logs": "retention_authorization_decision_logs_days",
    "activity_timeline_events": "retention_activity_timeline_events_days",
    "webhook_deliveries": "retention_webhook_deliveries_days",
}

_logger = get_logger("events.maintenance")


def effective_audit_retention_days(
    override_days: int | None, platform_days: int | None
) -> int | None:
    """Organisation override when set, else the platform default; ``None`` keeps every row."""
    return override_days if override_days is not None else platform_days


@dataclass(frozen=True)
class RetentionConfig:
    enabled: bool
    windows: Mapping[str, int | None]
    batch_size: int
    max_batches_per_run: int

    @classmethod
    def from_settings(cls, source: Any = None) -> RetentionConfig:
        src = settings if source is None else source
        return cls(
            enabled=bool(src.retention_enabled),
            windows={
                table: getattr(src, attr) for table, attr in RETENTION_WINDOW_SETTINGS.items()
            },
            batch_size=int(src.retention_delete_batch_size),
            max_batches_per_run=int(src.retention_max_batches_per_run),
        )


@dataclass
class TableRetentionResult:
    table: str
    rows_deleted: int = 0
    batches: int = 0
    organizations_purged: int = 0
    truncated: bool = False


@dataclass
class RetentionRunResult:
    enabled: bool
    tables: list[TableRetentionResult] = field(default_factory=list)

    @property
    def rows_deleted(self) -> int:
        return sum(item.rows_deleted for item in self.tables)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rows_deleted": self.rows_deleted,
            "tables": {
                item.table: {
                    "rows_deleted": item.rows_deleted,
                    "batches": item.batches,
                    "organizations_purged": item.organizations_purged,
                    "truncated": item.truncated,
                }
                for item in self.tables
            },
        }


class RetentionService:
    def __init__(self, repository: RetentionRepository | None = None) -> None:
        self._repository = repository or RetentionRepository()

    async def purge(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        config: RetentionConfig | None = None,
        organization_ids: Sequence[UUID] | None = None,
    ) -> RetentionRunResult:
        """Purge every configured table; ``organization_ids`` limits the run to those orgs."""
        cfg = config or RetentionConfig.from_settings()
        if not cfg.enabled:
            _logger.info("maintenance.retention.disabled")
            return RetentionRunResult(enabled=False)

        result = RetentionRunResult(enabled=True)
        # An explicit empty list means "no organisation", never "every organisation".
        org_ids: list[UUID] | None = (
            list(organization_ids) if organization_ids is not None else None
        )
        for table in RETENTION_TABLES:
            windows = await self._windows_for_table(session, table=table, config=cfg)
            if windows is None:
                continue
            if org_ids is None:
                org_ids = await self._repository.list_organization_ids(session)
                await session.commit()
            table_result = await self._purge_table(
                session,
                table=table,
                organization_ids=org_ids,
                windows=windows,
                now=now,
                config=cfg,
            )
            result.tables.append(table_result)
            _logger.info(
                "maintenance.retention.table_purged",
                table=table,
                rows_deleted=table_result.rows_deleted,
                batches=table_result.batches,
                organizations_purged=table_result.organizations_purged,
                truncated=table_result.truncated,
            )
        return result

    async def _windows_for_table(
        self,
        session: AsyncSession,
        *,
        table: str,
        config: RetentionConfig,
    ) -> _OrgWindows | None:
        platform_days = config.windows.get(table)
        if table != AUDIT_LOGS_TABLE:
            return None if platform_days is None else _OrgWindows(platform_days, {})
        overrides = await self._repository.audit_retention_overrides(session)
        await session.commit()
        if platform_days is None and not overrides:
            return None
        return _OrgWindows(platform_days, overrides)

    async def _purge_table(
        self,
        session: AsyncSession,
        *,
        table: str,
        organization_ids: list[UUID],
        windows: _OrgWindows,
        now: datetime,
        config: RetentionConfig,
    ) -> TableRetentionResult:
        table_result = TableRetentionResult(table=table)
        for organization_id in organization_ids:
            days = windows.for_organization(organization_id)
            if days is None:
                continue
            cutoff = now - timedelta(days=days)
            org_deleted = 0
            while True:
                if table_result.batches >= config.max_batches_per_run:
                    table_result.truncated = True
                    break
                deleted = await self._repository.delete_batch(
                    session,
                    table_name=table,
                    organization_id=organization_id,
                    cutoff=cutoff,
                    batch_size=config.batch_size,
                )
                await session.commit()
                if deleted == 0:
                    break
                table_result.batches += 1
                org_deleted += deleted
                record_retention_rows_deleted(table, deleted)
                if deleted < config.batch_size:
                    break
            if org_deleted:
                table_result.rows_deleted += org_deleted
                table_result.organizations_purged += 1
                _logger.info(
                    "maintenance.retention.organization_purged",
                    table=table,
                    organization_id=str(organization_id),
                    rows_deleted=org_deleted,
                    window_days=days,
                )
            if table_result.truncated:
                break
        return table_result


@dataclass(frozen=True)
class _OrgWindows:
    platform_days: int | None
    overrides: Mapping[UUID, int]

    def for_organization(self, organization_id: UUID) -> int | None:
        return effective_audit_retention_days(
            self.overrides.get(organization_id), self.platform_days
        )


def partition_drop_window_days(
    table: str,
    *,
    config: RetentionConfig,
    audit_overrides: Mapping[UUID, int],
) -> int | None:
    """Window after which a whole monthly partition may be dropped; ``None`` keeps it.

    A partition holds every organisation's rows, so for audit logs it is the longest
    effective window: the platform default or any longer organisation override. When the
    platform default is "keep", some organisation keeps everything and nothing is dropped.
    """
    if not config.enabled:
        return None
    platform_days = config.windows.get(table)
    if platform_days is None:
        return None
    if table != AUDIT_LOGS_TABLE or not audit_overrides:
        return platform_days
    return max(platform_days, *audit_overrides.values())
