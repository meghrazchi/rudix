from __future__ import annotations

from enum import StrEnum


class ConnectorAuditAction(StrEnum):
    connection_created = "connector.connection.created"
    connection_deleted = "connector.connection.deleted"
    connection_disconnected = "connector.connection.disconnected"
    oauth_connect_started = "connector.oauth.connect_started"
    oauth_connected = "connector.oauth.connected"
    oauth_reconnected = "connector.oauth.reconnected"
    oauth_callback_failed = "connector.oauth.callback_failed"
    oauth_refresh_failed = "connector.oauth.refresh_failed"
    oauth_token_refreshed = "connector.oauth.token_refreshed"
    source_selected = "connector.source.selected"
    source_permission_changed = "connector.source.permission_changed"
    source_deleted = "connector.source.deleted"
    sync_job_created = "connector.sync.job.created"
    sync_job_status_changed = "connector.sync.job.status_changed"
    sync_manual_queued = "connector.sync.manual_queued"
    sync_started = "connector.sync.started"
    sync_retry_scheduled = "connector.sync.retry_scheduled"
    sync_succeeded = "connector.sync.succeeded"
    sync_failed = "connector.sync.failed"
    sync_item_skipped = "connector.sync.item.skipped"
    ingestion_failed = "connector.ingestion.failed"
    ingestion_skipped = "connector.ingestion.skipped"
    sync_conflict_detected = "connector.sync.conflict.detected"
    sync_conflict_resolved = "connector.sync.conflict.resolved"
    sync_full_resync_triggered = "connector.sync.full_resync.triggered"
