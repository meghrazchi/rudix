from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.schemas.observability import (
    ConnectorErrorSummary,
    ConnectorObservabilityRange,
    ConnectorPlatformStatus,
    ConnectorPlatformTotals,
    ConnectorProviderHealthSummary,
)
from app.domains.connectors.services.connector_service import is_connector_platform_enabled
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_source import SourceReference
from app.models.connector_sync import ConnectorSyncRun
from app.models.document import Document
from app.models.enums import ConnectorConnectionStatus, ConnectorSyncRunStatus, ExternalItemType
from app.models.usage import AuditLog

_DEFAULT_RANGE_DAYS = 30
_RUN_TERMINAL_STATUSES = {
    ConnectorSyncRunStatus.completed.value,
    ConnectorSyncRunStatus.failed.value,
    ConnectorSyncRunStatus.cancelled.value,
}
_RUN_SUCCESS_STATUSES = {ConnectorSyncRunStatus.completed.value}
_RUN_FAILURE_STATUSES = {ConnectorSyncRunStatus.failed.value}
_RUN_CANCELLED_STATUSES = {ConnectorSyncRunStatus.cancelled.value}
_FILE_ITEM_TYPES = {ExternalItemType.cloud_file.value, ExternalItemType.attachment.value}
_AUDIT_ACTIONS = frozenset(
    {
        ConnectorAuditAction.sync_retry_scheduled.value,
        ConnectorAuditAction.sync_item_skipped.value,
        ConnectorAuditAction.ingestion_skipped.value,
        ConnectorAuditAction.ingestion_failed.value,
        ConnectorAuditAction.oauth_refresh_failed.value,
    }
)


@dataclass(slots=True)
class ProviderHealthData:
    provider_key: str
    provider_display_name: str
    connection_count: int = 0
    active_connection_count: int = 0
    sync_job_count: int = 0
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    cancelled_runs: int = 0
    running_runs: int = 0
    rate_limited_runs: int = 0
    auth_failed_runs: int = 0
    skipped_items: int = 0
    ingestion_failures: int = 0
    retry_events: int = 0
    token_refresh_failures: int = 0
    citation_usage: int = 0
    connector_documents: int = 0
    connector_files: int = 0
    items_seen: int = 0
    items_upserted: int = 0
    items_deleted: int = 0
    run_latencies_ms: list[float] = field(default_factory=list)
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    error_codes: Counter[str] = field(default_factory=Counter)

    def add_connection(self, connection: ConnectorConnection) -> None:
        self.connection_count += 1
        if connection.status == ConnectorConnectionStatus.active.value:
            self.active_connection_count += 1
        self.sync_job_count += len(connection.sync_jobs or [])

    def add_run(self, run: ConnectorSyncRun) -> None:
        self.total_runs += 1
        self.items_seen += int(run.items_seen or 0)
        self.items_upserted += int(run.items_upserted or 0)
        self.items_deleted += int(run.items_deleted or 0)

        if run.status in _RUN_SUCCESS_STATUSES:
            self.successful_runs += 1
            if run.completed_at is not None:
                self.last_success_at = _max_datetime(self.last_success_at, run.completed_at)
        elif run.status in _RUN_FAILURE_STATUSES:
            self.failed_runs += 1
            if run.completed_at is not None:
                self.last_failure_at = _max_datetime(self.last_failure_at, run.completed_at)
        elif run.status in _RUN_CANCELLED_STATUSES:
            self.cancelled_runs += 1
        elif run.status not in _RUN_TERMINAL_STATUSES:
            self.running_runs += 1

        if run.started_at is not None and run.completed_at is not None:
            latency_ms = (run.completed_at - run.started_at).total_seconds() * 1000.0
            if latency_ms >= 0:
                self.run_latencies_ms.append(latency_ms)

        error_details = run.error_details_json if isinstance(run.error_details_json, dict) else {}
        error_code = error_details.get("code")
        if isinstance(error_code, str) and error_code:
            self.error_codes[error_code] += 1
            if error_code == "rate_limit":
                self.rate_limited_runs += 1
            elif error_code == "auth_error":
                self.auth_failed_runs += 1

    def add_document_counts(self, *, connector_documents: int, connector_files: int) -> None:
        self.connector_documents += connector_documents
        self.connector_files += connector_files

    def add_reference_count(self, count: int) -> None:
        self.citation_usage += count

    def add_audit_count(self, action: str, count: int) -> None:
        if action == ConnectorAuditAction.sync_retry_scheduled.value:
            self.retry_events += count
        elif action == ConnectorAuditAction.sync_item_skipped.value:
            self.skipped_items += count
        elif action == ConnectorAuditAction.ingestion_skipped.value:
            self.skipped_items += count
        elif action == ConnectorAuditAction.ingestion_failed.value:
            self.ingestion_failures += count
        elif action == ConnectorAuditAction.oauth_refresh_failed.value:
            self.token_refresh_failures += count

    def average_latency_ms(self) -> float | None:
        if not self.run_latencies_ms:
            return None
        return sum(self.run_latencies_ms) / len(self.run_latencies_ms)

    def health_status(self, *, platform_enabled: bool) -> ConnectorPlatformStatus:
        if not platform_enabled:
            return "disabled"
        if self.total_runs == 0 and self.connection_count == 0:
            return "unknown"
        if self.failed_runs > 0 or self.rate_limited_runs > 0 or self.auth_failed_runs > 0:
            return "degraded"
        if self.connection_count > 0 and self.active_connection_count == 0:
            return "degraded"
        return "healthy"

    def to_summary(self, *, platform_enabled: bool) -> ConnectorProviderHealthSummary:
        return ConnectorProviderHealthSummary(
            provider_key=self.provider_key,
            provider_display_name=self.provider_display_name,
            connection_count=self.connection_count,
            active_connection_count=self.active_connection_count,
            sync_job_count=self.sync_job_count,
            total_runs=self.total_runs,
            successful_runs=self.successful_runs,
            failed_runs=self.failed_runs,
            cancelled_runs=self.cancelled_runs,
            running_runs=self.running_runs,
            rate_limited_runs=self.rate_limited_runs,
            auth_failed_runs=self.auth_failed_runs,
            skipped_items=self.skipped_items,
            ingestion_failures=self.ingestion_failures,
            retry_events=self.retry_events,
            token_refresh_failures=self.token_refresh_failures,
            citation_usage=self.citation_usage,
            connector_documents=self.connector_documents,
            connector_files=self.connector_files,
            items_seen=self.items_seen,
            items_upserted=self.items_upserted,
            items_deleted=self.items_deleted,
            avg_run_latency_ms=self.average_latency_ms(),
            last_success_at=self.last_success_at,
            last_failure_at=self.last_failure_at,
            health_status=self.health_status(platform_enabled=platform_enabled),
            top_error_codes=[
                ConnectorErrorSummary(code=code, count=count)
                for code, count in self.error_codes.most_common(5)
            ],
        )


@dataclass(slots=True)
class ConnectorPlatformHealthSnapshot:
    organization_id: UUID
    range: ConnectorObservabilityRange
    generated_at: datetime
    feature_enabled: bool
    rollout_stage: str
    overall_status: ConnectorPlatformStatus
    totals: ConnectorPlatformTotals
    providers: list[ConnectorProviderHealthSummary]


class ConnectorPlatformObservabilityService:
    async def build_health_snapshot(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> ConnectorPlatformHealthSnapshot:
        resolved_to = to_date or datetime.now(tz=UTC).date()
        resolved_from = from_date or (resolved_to - timedelta(days=_DEFAULT_RANGE_DAYS - 1))
        if resolved_from > resolved_to:
            raise ValueError("from must be less than or equal to to")

        start_dt = datetime.combine(resolved_from, time.min, tzinfo=UTC)
        end_dt = datetime.combine(resolved_to, time.max, tzinfo=UTC)
        platform_enabled = is_connector_platform_enabled()

        providers = await self._load_provider_metrics(
            session,
            organization_id=organization_id,
            start_dt=start_dt,
            end_dt=end_dt,
            platform_enabled=platform_enabled,
        )
        totals = self._build_totals(providers)
        overall_status = self._determine_overall_status(platform_enabled, providers)

        return ConnectorPlatformHealthSnapshot(
            organization_id=organization_id,
            range=ConnectorObservabilityRange(from_date=resolved_from, to_date=resolved_to),
            generated_at=datetime.now(tz=UTC),
            feature_enabled=platform_enabled,
            rollout_stage=settings.connector_rollout_stage.value,
            overall_status=overall_status,
            totals=totals,
            providers=[
                provider.to_summary(platform_enabled=platform_enabled)
                for provider in providers.values()
            ],
        )

    async def _load_provider_metrics(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        start_dt: datetime,
        end_dt: datetime,
        platform_enabled: bool,
    ) -> dict[str, ProviderHealthData]:
        provider_result = await session.execute(
            select(ConnectorConnection)
            .options(
                selectinload(ConnectorConnection.provider),
                selectinload(ConnectorConnection.sync_jobs),
            )
            .where(ConnectorConnection.organization_id == organization_id)
        )
        providers: dict[str, ProviderHealthData] = {}
        for connection in provider_result.scalars().all():
            provider = connection.provider
            if provider is None:
                continue
            data = providers.setdefault(
                provider.key,
                ProviderHealthData(
                    provider_key=provider.key,
                    provider_display_name=provider.display_name,
                ),
            )
            data.add_connection(connection)

        run_result = await session.execute(
            select(ConnectorSyncRun)
            .options(
                selectinload(ConnectorSyncRun.connection).selectinload(ConnectorConnection.provider)
            )
            .where(
                ConnectorSyncRun.organization_id == organization_id,
                ConnectorSyncRun.created_at >= start_dt,
                ConnectorSyncRun.created_at <= end_dt,
            )
        )
        for run in run_result.scalars().all():
            provider = run.connection.provider if run.connection else None
            if provider is None:
                continue
            data = providers.setdefault(
                provider.key,
                ProviderHealthData(
                    provider_key=provider.key,
                    provider_display_name=provider.display_name,
                ),
            )
            data.add_run(run)

        document_result = await session.execute(
            select(
                ConnectorProvider.key,
                Document.id,
                ExternalItem.item_type,
            )
            .select_from(Document)
            .join(
                ExternalItem,
                ExternalItem.id == Document.connector_external_item_id,
            )
            .join(
                ConnectorConnection,
                ConnectorConnection.id == ExternalItem.connection_id,
            )
            .join(
                ConnectorProvider,
                ConnectorProvider.id == ConnectorConnection.provider_id,
            )
            .where(
                Document.organization_id == organization_id,
                Document.ingestion_source == "connector",
            )
        )
        connector_document_counts: dict[str, int] = {}
        connector_file_counts: dict[str, int] = {}
        for provider_key, _document_id, item_type in document_result.all():
            connector_document_counts[provider_key] = (
                connector_document_counts.get(provider_key, 0) + 1
            )
            if item_type in _FILE_ITEM_TYPES:
                connector_file_counts[provider_key] = connector_file_counts.get(provider_key, 0) + 1

        reference_result = await session.execute(
            select(ConnectorProvider.key, SourceReference.id)
            .select_from(SourceReference)
            .join(
                ExternalItem,
                ExternalItem.id == SourceReference.external_item_id,
            )
            .join(
                ConnectorConnection,
                ConnectorConnection.id == ExternalItem.connection_id,
            )
            .join(
                ConnectorProvider,
                ConnectorProvider.id == ConnectorConnection.provider_id,
            )
            .where(SourceReference.organization_id == organization_id)
        )
        citation_counts: dict[str, int] = {}
        for provider_key, _reference_id in reference_result.all():
            citation_counts[provider_key] = citation_counts.get(provider_key, 0) + 1

        audit_result = await session.execute(
            select(AuditLog)
            .where(
                AuditLog.organization_id == organization_id,
                AuditLog.created_at >= start_dt,
                AuditLog.created_at <= end_dt,
                AuditLog.action.in_(_AUDIT_ACTIONS),
            )
            .order_by(AuditLog.created_at.asc())
        )
        for row in audit_result.scalars().all():
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            provider_key = metadata.get("provider_key")
            if isinstance(provider_key, str) and provider_key in providers:
                providers[provider_key].add_audit_count(row.action, 1)

        for data in providers.values():
            data.add_document_counts(
                connector_documents=connector_document_counts.get(data.provider_key, 0),
                connector_files=connector_file_counts.get(data.provider_key, 0),
            )
            data.add_reference_count(citation_counts.get(data.provider_key, 0))
            if not platform_enabled and data.connection_count > 0:
                data.last_failure_at = data.last_failure_at or datetime.now(tz=UTC)

        return providers

    def _build_totals(
        self,
        providers: dict[str, ProviderHealthData],
    ) -> ConnectorPlatformTotals:
        totals = ConnectorPlatformTotals(
            connection_count=0,
            active_connection_count=0,
            sync_job_count=0,
            total_runs=0,
            successful_runs=0,
            failed_runs=0,
            cancelled_runs=0,
            running_runs=0,
            rate_limited_runs=0,
            auth_failed_runs=0,
            skipped_items=0,
            ingestion_failures=0,
            retry_events=0,
            token_refresh_failures=0,
            citation_usage=0,
            connector_documents=0,
            connector_files=0,
            items_seen=0,
            items_upserted=0,
            items_deleted=0,
            avg_run_latency_ms=None,
        )
        latencies: list[float] = []
        for provider in providers.values():
            totals.connection_count += provider.connection_count
            totals.active_connection_count += provider.active_connection_count
            totals.sync_job_count += provider.sync_job_count
            totals.total_runs += provider.total_runs
            totals.successful_runs += provider.successful_runs
            totals.failed_runs += provider.failed_runs
            totals.cancelled_runs += provider.cancelled_runs
            totals.running_runs += provider.running_runs
            totals.rate_limited_runs += provider.rate_limited_runs
            totals.auth_failed_runs += provider.auth_failed_runs
            totals.skipped_items += provider.skipped_items
            totals.ingestion_failures += provider.ingestion_failures
            totals.retry_events += provider.retry_events
            totals.token_refresh_failures += provider.token_refresh_failures
            totals.citation_usage += provider.citation_usage
            totals.connector_documents += provider.connector_documents
            totals.connector_files += provider.connector_files
            totals.items_seen += provider.items_seen
            totals.items_upserted += provider.items_upserted
            totals.items_deleted += provider.items_deleted
            latencies.extend(provider.run_latencies_ms)
        if latencies:
            totals.avg_run_latency_ms = sum(latencies) / len(latencies)
        return totals

    def _determine_overall_status(
        self,
        platform_enabled: bool,
        providers: dict[str, ProviderHealthData],
    ) -> ConnectorPlatformStatus:
        if not platform_enabled:
            return "disabled"
        if not providers:
            return "unknown"
        if any(
            provider.health_status(platform_enabled=platform_enabled) == "degraded"
            for provider in providers.values()
        ):
            return "degraded"
        return "healthy"


def _max_datetime(current: datetime | None, candidate: datetime) -> datetime:
    if current is None or candidate > current:
        return candidate
    return current
