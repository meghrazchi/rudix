"""Beat task that exports backup freshness from the markers (R08-06).

``ops.backups.check_freshness`` runs every ``BACKUP_FRESHNESS_INTERVAL_SECONDS`` and is a
no-op unless ``BACKUP_FRESHNESS_CHECK_ENABLED=true``. It reads ``<prefix>/<kind>/latest.json``
for every kind in ``BACKUP_KINDS`` and sets ``rudix_backup_last_success_timestamp_seconds``
and ``rudix_backup_freshness_checks_total`` (alerts in ``rules/backups.yml``). It never
raises: a bucket error is counted as ``outcome="error"`` and logged with its type only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.ops.backup.freshness import check_freshness, count_check, record_freshness
from app.ops.backup.store import BackupStore
from app.workers.base_task import RudixTask
from app.workers.celery_app import celery_app

logger = get_logger("workers.backup")

# Indirection so tests inject a store over a fake S3 client.
store_factory: Callable[[], BackupStore] = lambda: BackupStore.from_settings(  # noqa: E731
    settings, require_enabled=False
)


def run_freshness_check() -> dict[str, Any]:
    if not settings.backup_freshness_check_enabled:
        return {"status": "disabled"}
    try:
        store = store_factory()
        results = check_freshness(
            store, settings.backup_kinds, max_age_hours=settings.backup_max_age_hours
        )
    except Exception as exc:
        count_check("error")
        logger.error("backup.freshness.check_failed", error=type(exc).__name__)
        return {"status": "error"}
    outcome = record_freshness(results)
    log = logger.info if outcome == "fresh" else logger.warning
    log(
        "backup.freshness.checked",
        outcome=outcome,
        kinds={result.kind: result.status for result in results},
    )
    return {
        "status": outcome,
        "kinds": {
            result.kind: {
                "status": result.status,
                "age_seconds": None if result.age_seconds is None else round(result.age_seconds, 1),
            }
            for result in results
        },
    }


@celery_app.task(name="ops.backups.check_freshness", bind=True, base=RudixTask, ignore_result=True)
def check_backup_freshness_task(self: RudixTask) -> dict[str, Any]:
    """Export the age of the newest backup of each kind."""
    return run_freshness_check()
