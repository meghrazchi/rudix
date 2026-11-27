"""Types and helpers shared by the connector sync modules (R06-11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import ExternalItemType

DEFAULT_PAGE_SIZE = 100
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 60 * 24 * 7

# Item types whose content should be downloaded and ingested as Documents.
FILE_ITEM_TYPES: frozenset[str] = frozenset(
    {ExternalItemType.cloud_file, ExternalItemType.attachment, ExternalItemType.wiki_page}
)


@dataclass
class SyncRunResult:
    sync_run_id: UUID
    status: str
    items_seen: int
    items_upserted: int
    items_deleted: int
    cursor_after: dict
    error_message: str | None = None
    # Deprecated in 0.6.0: documents are dispatched through the outbox as each page
    # commits, so this stays empty. Kept for one milestone for callers that read it.
    pending_document_ids: list[tuple[str, str]] = field(default_factory=list)
    # 0.6.0: seconds after which the task should run the same run again (rate limit
    # longer than the inline backoff, or a concurrency cap), else None.
    requeue_after_seconds: int | None = None
    pages_committed: int = 0


class SyncEngineError(Exception):
    """Raised for engine-level validation failures (not task-level retries)."""


def schedule_interval_minutes(job: ConnectorSyncJob) -> int | None:
    """Interval of an interval schedule clamped to 5..10080 minutes; None for manual_only."""
    schedule = job.schedule_json or {}
    if schedule.get("type", "interval") == "manual_only":
        return None
    interval_minutes = int(schedule.get("interval_minutes", 60))
    return max(MIN_INTERVAL_MINUTES, min(interval_minutes, MAX_INTERVAL_MINUTES))


def next_run_due(job: ConnectorSyncJob, now: datetime) -> bool:
    interval_minutes = schedule_interval_minutes(job)
    if interval_minutes is None:
        return False
    if job.last_run_at is None:
        return True
    last_run = job.last_run_at
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=UTC)
    return now >= last_run + timedelta(minutes=interval_minutes)


def source_id_str(run: ConnectorSyncRun) -> str | None:
    return str(run.external_source_id) if run.external_source_id else None
