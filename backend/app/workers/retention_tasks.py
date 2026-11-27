"""Daily retention and partition maintenance beat tasks (R04-09).

* ``maintenance.retention.purge`` (03:15 UTC): batched per-organisation deletes for the tables
  with a ``RETENTION_<TABLE>_DAYS`` window (see ``RetentionService``). Every default is
  "keep", so the task deletes nothing until an operator sets a window.
* ``maintenance.partitions.ensure`` (03:45 UTC): for retention tables that are already
  partitioned (none today), creates this and next month's partitions, drops partitions past
  the retention window, and sets ``rudix_partition_missing{table}``. Unpartitioned tables are
  skipped.

Both are cross-tenant, so they use ``maintenance_session()``, and both are idempotent: a
rerun finds nothing left to delete or create.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.logging import get_logger
from app.db.partitioning import (
    drop_expired_partitions,
    ensure_future_partitions,
    report_missing_partition,
)
from app.db.session import maintenance_session
from app.domains.admin.repositories.retention import RETENTION_TABLES, RetentionRepository
from app.domains.admin.services.retention_service import (
    RetentionConfig,
    RetentionService,
    partition_drop_window_days,
)
from app.workers.async_runtime import run_async
from app.workers.base_task import RudixTask
from app.workers.celery_app import celery_app

_logger = get_logger("events.maintenance")
_retention_service = RetentionService()
_retention_repository = RetentionRepository()


async def _purge_async(now: datetime) -> dict[str, Any]:
    async with maintenance_session() as session:
        result = await _retention_service.purge(session, now=now)
    return result.as_dict()


async def _ensure_table(table: str, *, now: datetime, config: RetentionConfig) -> dict[str, Any]:
    async with maintenance_session() as session:
        conn = await session.connection()
        ensured = await ensure_future_partitions(conn, table, now=now)
        if not ensured.partitioned:
            await session.rollback()
            return {"partitioned": False}
        overrides = await _retention_repository.audit_retention_overrides(session)
        window = partition_drop_window_days(table, config=config, audit_overrides=overrides)
        dropped: list[str] = []
        if window is not None:
            dropped = await drop_expired_partitions(
                conn, table, cutoff=now - timedelta(days=window)
            )
        await session.commit()
    return {
        "partitioned": True,
        "created": list(ensured.created),
        "dropped": dropped,
        "next_month_missing": ensured.next_month_missing,
    }


async def _report_after_failure(table: str, *, now: datetime) -> None:
    try:
        async with maintenance_session() as session:
            await report_missing_partition(await session.connection(), table, now=now)
            await session.rollback()
    except Exception as exc:
        _logger.warning(
            "maintenance.partitions.report_failed", table=table, error_type=type(exc).__name__
        )


async def _ensure_partitions_async(now: datetime) -> dict[str, Any]:
    config = RetentionConfig.from_settings()
    tables: dict[str, Any] = {}
    failed = 0
    for table in RETENTION_TABLES:
        try:
            tables[table] = await _ensure_table(table, now=now, config=config)
        except Exception as exc:
            failed += 1
            tables[table] = {"error_type": type(exc).__name__}
            _logger.warning(
                "maintenance.partitions.ensure_failed",
                table=table,
                error_type=type(exc).__name__,
            )
            await _report_after_failure(table, now=now)
    return {"tables": tables, "failed": failed}


@celery_app.task(name="maintenance.retention.purge", bind=True, base=RudixTask, ignore_result=True)
def purge_retention(self: RudixTask) -> dict[str, Any]:
    """Delete rows past their retention window, per organisation, in batches."""
    return run_async(_purge_async(datetime.now(UTC)))


@celery_app.task(
    name="maintenance.partitions.ensure", bind=True, base=RudixTask, ignore_result=True
)
def ensure_partitions(self: RudixTask) -> dict[str, Any]:
    """Create upcoming monthly partitions and drop expired ones on partitioned tables."""
    return run_async(_ensure_partitions_async(datetime.now(UTC)))
