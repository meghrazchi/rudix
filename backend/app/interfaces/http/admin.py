from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.schemas.admin import (
    AgentDiagnosticsPointResponse,
    AgentDiagnosticsResponse,
    AgentDiagnosticsTotalsResponse,
    AuditExportFormat,
    AuditLogListItemResponse,
    AuditLogListResponse,
    AuditResultFilter,
    FeatureArea,
    TopModelUsageResponse,
    TopUserUsageResponse,
    UsageDashboardPointResponse,
    UsageDashboardResponse,
    UsageDashboardTotalsResponse,
    UsageExportFormat,
    UsageGranularity,
    UsageSummaryPointResponse,
    UsageSummaryRange,
    UsageSummaryResponse,
    UsageSummaryTotalsResponse,
)
from dataclasses import field as dataclass_field

from app.domains.admin.services.audit_service import sanitize_metadata
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.usage import AuditLog, UsageEvent
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin", tags=["admin"])
usage_repository = UsageRepository()

DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 365

CONFIDENCE_KEYS = (
    "confidence_score",
    "confidence",
    "answer_confidence",
)

LATENCY_KEYS = (
    "latency_ms",
    "answer_latency_ms",
    "total_latency_ms",
)

AGENT_RUNTIME_EVENT_TYPE = "agent.runtime"
AGENT_TOOL_CALL_EVENT_TYPE = "agent.tool_call"
AGENT_APPROVAL_EVENT_TYPE = "agent.approval"
AGENT_EVENT_TYPES = {
    AGENT_RUNTIME_EVENT_TYPE,
    AGENT_TOOL_CALL_EVENT_TYPE,
    AGENT_APPROVAL_EVENT_TYPE,
}

AUDIT_SUCCESS_RESULTS = frozenset({"ok", "success", "succeeded", "completed"})
AUDIT_FAILURE_RESULTS = frozenset({"failed", "failure", "error", "denied", "rejected"})


def _organization_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal organization context is invalid",
        ) from exc


def _normalize_date_range(
    *,
    from_date: date | None,
    to_date: date | None,
) -> tuple[date, date]:
    today = datetime.now(tz=UTC).date()
    resolved_to = to_date or today
    resolved_from = from_date or (resolved_to - timedelta(days=DEFAULT_RANGE_DAYS - 1))

    if resolved_from > resolved_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from must be less than or equal to to",
        )

    range_days = (resolved_to - resolved_from).days + 1
    if range_days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date range exceeds maximum of {MAX_RANGE_DAYS} days",
        )

    return resolved_from, resolved_to


def _to_datetime_bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(from_date, time.min, tzinfo=UTC)
    end = datetime.combine(to_date, time.max, tzinfo=UTC)
    return start, end


def _extract_numeric(metadata: dict[str, object], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            candidate = float(value)
            if candidate == candidate:  # NaN guard
                return candidate
    return None


def _extract_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            return candidate
    return None


def _latency_score_from_average(avg_latency_ms: float | None) -> float | None:
    if avg_latency_ms is None:
        return None
    # Keep the existing dashboard scoring model stable while moving computation server-side.
    return max(0.0, min(100.0, 100.0 - (avg_latency_ms / 12.0)))


def _bucket_period_start(value: datetime, granularity: UsageGranularity) -> date:
    value_date = value.astimezone(UTC).date()
    if granularity == "day":
        return value_date
    if granularity == "week":
        return value_date - timedelta(days=value_date.weekday())
    return date(value_date.year, value_date.month, 1)


def _bucket_period_end(start: date, granularity: UsageGranularity) -> date:
    if granularity == "day":
        return start
    if granularity == "week":
        return start + timedelta(days=6)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    return next_month - timedelta(days=1)


@dataclass
class _BucketAccumulator:
    period_start: date
    period_end: date
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    event_count: int = 0
    confidence_values: list[float] | None = None
    latency_values: list[float] | None = None

    def add_event(self, event: UsageEvent) -> None:
        self.input_tokens += max(0, int(event.input_tokens or 0))
        self.output_tokens += max(0, int(event.output_tokens or 0))
        self.cost_usd += event.cost_usd or Decimal("0")
        self.event_count += 1

        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        confidence = _extract_numeric(metadata, CONFIDENCE_KEYS)
        if confidence is not None:
            if self.confidence_values is None:
                self.confidence_values = []
            self.confidence_values.append(confidence)

        latency = _extract_numeric(metadata, LATENCY_KEYS)
        if latency is not None:
            if self.latency_values is None:
                self.latency_values = []
            self.latency_values.append(max(0.0, latency))

    def average_confidence(self) -> float | None:
        if not self.confidence_values:
            return None
        return sum(self.confidence_values) / len(self.confidence_values)

    def average_latency_ms(self) -> float | None:
        if not self.latency_values:
            return None
        return sum(self.latency_values) / len(self.latency_values)


def _aggregate_usage(
    events: list[UsageEvent],
    *,
    granularity: UsageGranularity,
) -> tuple[UsageSummaryTotalsResponse, list[UsageSummaryPointResponse]]:
    buckets: dict[date, _BucketAccumulator] = {}
    total = _BucketAccumulator(period_start=date.min, period_end=date.min)

    for event in events:
        bucket_start = _bucket_period_start(event.created_at, granularity)
        bucket = buckets.get(bucket_start)
        if bucket is None:
            bucket = _BucketAccumulator(
                period_start=bucket_start,
                period_end=_bucket_period_end(bucket_start, granularity),
            )
            buckets[bucket_start] = bucket

        bucket.add_event(event)
        total.add_event(event)

    series: list[UsageSummaryPointResponse] = []
    for _, bucket in sorted(buckets.items(), key=lambda item: item[0]):
        avg_confidence = bucket.average_confidence()
        avg_latency_ms = bucket.average_latency_ms()
        series.append(
            UsageSummaryPointResponse(
                period_start=bucket.period_start,
                period_end=bucket.period_end,
                input_tokens=bucket.input_tokens,
                output_tokens=bucket.output_tokens,
                cost_usd=float(bucket.cost_usd),
                event_count=bucket.event_count,
                avg_confidence=avg_confidence,
                avg_latency_ms=avg_latency_ms,
                latency_score=_latency_score_from_average(avg_latency_ms),
            )
        )

    total_avg_confidence = total.average_confidence()
    total_avg_latency_ms = total.average_latency_ms()
    totals = UsageSummaryTotalsResponse(
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        cost_usd=float(total.cost_usd),
        event_count=total.event_count,
        avg_confidence=total_avg_confidence,
        avg_latency_ms=total_avg_latency_ms,
        latency_score=_latency_score_from_average(total_avg_latency_ms),
    )

    return totals, series


@dataclass
class _AgentDiagnosticsAccumulator:
    period_start: date
    period_end: date
    runs_started: int = 0
    runs_completed: int = 0
    runs_failed: int = 0
    runs_waiting_approval: int = 0
    runs_cancelled: int = 0
    steps_executed: int = 0
    tool_calls_executed: int = 0
    tool_calls_succeeded: int = 0
    tool_calls_failed: int = 0
    approvals_requested: int = 0
    approvals_approved: int = 0
    approvals_rejected: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    confidence_values: list[float] | None = None

    def add_event(self, event: UsageEvent) -> None:
        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        event_type = event.event_type
        if event_type == AGENT_RUNTIME_EVENT_TYPE:
            status = _extract_text(metadata, "status")
            if status == "completed":
                self.runs_completed += 1
            elif status == "failed":
                self.runs_failed += 1
            elif status == "waiting_approval":
                self.runs_waiting_approval += 1
            elif status == "cancelled":
                self.runs_cancelled += 1
            else:
                self.runs_started += 1
            self.steps_executed += max(0, int(metadata.get("steps_executed", 0) or 0))
            self.tool_calls_executed += max(0, int(metadata.get("tool_calls_executed", 0) or 0))
            self.total_tokens += max(
                0, int(event.input_tokens or 0) + int(event.output_tokens or 0)
            )
            self.total_cost_usd += event.cost_usd or Decimal("0")
            confidence = _extract_numeric(metadata, CONFIDENCE_KEYS)
            if confidence is not None:
                if self.confidence_values is None:
                    self.confidence_values = []
                self.confidence_values.append(confidence)
            return

        if event_type == AGENT_TOOL_CALL_EVENT_TYPE:
            success_value = metadata.get("success")
            success = success_value is True
            if success:
                self.tool_calls_succeeded += 1
            else:
                self.tool_calls_failed += 1
            return

        if event_type == AGENT_APPROVAL_EVENT_TYPE:
            status = _extract_text(metadata, "status")
            if status == "approved":
                self.approvals_approved += 1
            elif status == "rejected":
                self.approvals_rejected += 1
            else:
                self.approvals_requested += 1

    def average_confidence(self) -> float | None:
        if not self.confidence_values:
            return None
        return sum(self.confidence_values) / len(self.confidence_values)


def _aggregate_agent_diagnostics(
    events: list[UsageEvent],
    *,
    granularity: UsageGranularity,
) -> tuple[AgentDiagnosticsTotalsResponse, list[AgentDiagnosticsPointResponse], dict[str, int]]:
    buckets: dict[date, _AgentDiagnosticsAccumulator] = {}
    total = _AgentDiagnosticsAccumulator(period_start=date.min, period_end=date.min)
    errors_by_code: dict[str, int] = {}

    for event in events:
        bucket_start = _bucket_period_start(event.created_at, granularity)
        bucket = buckets.get(bucket_start)
        if bucket is None:
            bucket = _AgentDiagnosticsAccumulator(
                period_start=bucket_start,
                period_end=_bucket_period_end(bucket_start, granularity),
            )
            buckets[bucket_start] = bucket
        bucket.add_event(event)
        total.add_event(event)
        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        error_code = _extract_text(metadata, "error_code")
        if error_code:
            errors_by_code[error_code] = errors_by_code.get(error_code, 0) + 1

    series = [
        AgentDiagnosticsPointResponse(
            period_start=bucket.period_start,
            period_end=bucket.period_end,
            runs_started=bucket.runs_started,
            runs_completed=bucket.runs_completed,
            runs_failed=bucket.runs_failed,
            runs_waiting_approval=bucket.runs_waiting_approval,
            runs_cancelled=bucket.runs_cancelled,
            steps_executed=bucket.steps_executed,
            tool_calls_executed=bucket.tool_calls_executed,
            tool_calls_succeeded=bucket.tool_calls_succeeded,
            tool_calls_failed=bucket.tool_calls_failed,
            approvals_requested=bucket.approvals_requested,
            approvals_approved=bucket.approvals_approved,
            approvals_rejected=bucket.approvals_rejected,
            total_tokens=bucket.total_tokens,
            total_cost_usd=float(bucket.total_cost_usd),
            avg_confidence=bucket.average_confidence(),
        )
        for _, bucket in sorted(buckets.items(), key=lambda item: item[0])
    ]

    totals = AgentDiagnosticsTotalsResponse(
        runs_started=total.runs_started,
        runs_completed=total.runs_completed,
        runs_failed=total.runs_failed,
        runs_waiting_approval=total.runs_waiting_approval,
        runs_cancelled=total.runs_cancelled,
        steps_executed=total.steps_executed,
        tool_calls_executed=total.tool_calls_executed,
        tool_calls_succeeded=total.tool_calls_succeeded,
        tool_calls_failed=total.tool_calls_failed,
        approvals_requested=total.approvals_requested,
        approvals_approved=total.approvals_approved,
        approvals_rejected=total.approvals_rejected,
        total_tokens=total.total_tokens,
        total_cost_usd=float(total.total_cost_usd),
        avg_confidence=total.average_confidence(),
    )
    return totals, series, errors_by_code


_FEATURE_AREA_PREFIXES: dict[str, str] = {
    "agent": "agent",
    "evaluation": "evaluation",
    "pipeline": "pipeline",
    "api": "api",
}

_FEATURE_AREA_TO_PREFIX: dict[str, str] = {
    "chat": "chat",
    "agent": "agent",
    "evaluation": "evaluation",
    "pipeline": "pipeline",
    "api": "api",
}


def _event_feature_area(event_type: str) -> str:
    if not event_type:
        return "other"
    prefix = event_type.split(".")[0]
    return prefix if prefix in _FEATURE_AREA_TO_PREFIX else "other"


@dataclass
class _DashboardBucketAccumulator:
    period_start: date
    period_end: date
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")
    questions_asked: int = 0
    agent_runs: int = 0
    evaluation_runs: int = 0
    indexing_jobs: int = 0
    failed_indexing_jobs: int = 0
    api_calls: int = 0
    user_ids: set = dataclass_field(default_factory=set)
    confidence_values: list[float] | None = None
    latency_values: list[float] | None = None

    def add_event(self, event: UsageEvent) -> None:
        self.input_tokens += max(0, int(event.input_tokens or 0))
        self.output_tokens += max(0, int(event.output_tokens or 0))
        self.estimated_cost_usd += event.cost_usd or Decimal("0")
        if event.user_id is not None:
            self.user_ids.add(str(event.user_id))

        event_type = event.event_type or ""
        area = _event_feature_area(event_type)
        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}

        if area == "agent" and event_type == AGENT_RUNTIME_EVENT_TYPE:
            self.agent_runs += 1
        elif area == "evaluation":
            self.evaluation_runs += 1
        elif area == "pipeline":
            if _extract_text(metadata, "status") == "failed":
                self.failed_indexing_jobs += 1
            else:
                self.indexing_jobs += 1
        elif area == "api":
            self.api_calls += 1
        else:
            self.questions_asked += 1

        confidence = _extract_numeric(metadata, CONFIDENCE_KEYS)
        if confidence is not None:
            if self.confidence_values is None:
                self.confidence_values = []
            self.confidence_values.append(confidence)

        latency = _extract_numeric(metadata, LATENCY_KEYS)
        if latency is not None:
            if self.latency_values is None:
                self.latency_values = []
            self.latency_values.append(max(0.0, latency))

    def active_users(self) -> int:
        return len(self.user_ids)

    def average_confidence(self) -> float | None:
        if not self.confidence_values:
            return None
        return sum(self.confidence_values) / len(self.confidence_values)

    def average_latency_ms(self) -> float | None:
        if not self.latency_values:
            return None
        return sum(self.latency_values) / len(self.latency_values)


def _aggregate_dashboard(
    events: list[UsageEvent],
    *,
    granularity: UsageGranularity,
) -> tuple[_DashboardBucketAccumulator, list[UsageDashboardPointResponse]]:
    buckets: dict[date, _DashboardBucketAccumulator] = {}
    total = _DashboardBucketAccumulator(period_start=date.min, period_end=date.min)

    for event in events:
        bucket_start = _bucket_period_start(event.created_at, granularity)
        bucket = buckets.get(bucket_start)
        if bucket is None:
            bucket = _DashboardBucketAccumulator(
                period_start=bucket_start,
                period_end=_bucket_period_end(bucket_start, granularity),
            )
            buckets[bucket_start] = bucket
        bucket.add_event(event)
        total.add_event(event)

    series: list[UsageDashboardPointResponse] = [
        UsageDashboardPointResponse(
            period_start=b.period_start,
            period_end=b.period_end,
            questions_asked=b.questions_asked,
            input_tokens=b.input_tokens,
            output_tokens=b.output_tokens,
            estimated_cost_usd=float(b.estimated_cost_usd),
            active_users=b.active_users(),
            agent_runs=b.agent_runs,
            evaluation_runs=b.evaluation_runs,
            avg_confidence=b.average_confidence(),
            avg_latency_ms=b.average_latency_ms(),
        )
        for _, b in sorted(buckets.items(), key=lambda item: item[0])
    ]

    return total, series


async def _count_org_documents(
    db_session: AsyncSession,
    organization_id: UUID,
) -> tuple[int, int, int]:
    """Returns (total_docs, indexed_docs, total_chunks)."""
    non_deleted = ("deleted",)
    total_stmt = select(func.count(Document.id)).where(
        Document.organization_id == organization_id,
        Document.status.not_in(non_deleted),
    )
    indexed_stmt = select(func.count(Document.id)).where(
        Document.organization_id == organization_id,
        Document.status == "indexed",
    )
    chunks_stmt = select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
        Document.organization_id == organization_id,
        Document.status == "indexed",
    )
    total_docs = int((await db_session.execute(total_stmt)).scalar_one() or 0)
    indexed_docs = int((await db_session.execute(indexed_stmt)).scalar_one() or 0)
    total_chunks = int((await db_session.execute(chunks_stmt)).scalar_one() or 0)
    return total_docs, indexed_docs, total_chunks


def _serialize_usage_events_csv(events: list[UsageEvent]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "created_at",
            "organization_id",
            "user_id",
            "event_type",
            "model_name",
            "input_tokens",
            "output_tokens",
            "estimated_cost_usd",
        ],
    )
    writer.writeheader()
    for e in events:
        writer.writerow(
            {
                "id": str(e.id),
                "created_at": e.created_at.isoformat(),
                "organization_id": str(e.organization_id),
                "user_id": str(e.user_id) if e.user_id else "",
                "event_type": e.event_type,
                "model_name": e.model_name or "",
                "input_tokens": e.input_tokens if e.input_tokens is not None else "",
                "output_tokens": e.output_tokens if e.output_tokens is not None else "",
                "estimated_cost_usd": str(e.cost_usd) if e.cost_usd is not None else "",
            }
        )
    return output.getvalue()


@router.get("/usage/dashboard", response_model=UsageDashboardResponse)
async def get_admin_usage_dashboard(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    granularity: UsageGranularity = "day",
    user_id: UUID | None = None,
    model: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    feature_area: FeatureArea = "all",
) -> UsageDashboardResponse:
    organization_id = _organization_id_from_principal(principal)
    resolved_from, resolved_to = _normalize_date_range(from_date=from_date, to_date=to_date)
    from_created_at, to_created_at = _to_datetime_bounds(resolved_from, resolved_to)

    event_type_prefix: str | None = None
    if feature_area != "all":
        event_type_prefix = _FEATURE_AREA_TO_PREFIX.get(feature_area)

    events = await usage_repository.list_usage_events_filtered(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=user_id,
        model_name=model,
        event_type_prefix=event_type_prefix,
    )

    total_bucket, series = _aggregate_dashboard(events, granularity=granularity)
    total_docs, indexed_docs, total_chunks = await _count_org_documents(db_session, organization_id)

    top_user_rows = await usage_repository.aggregate_by_user(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
    )
    top_users = [
        TopUserUsageResponse(
            user_id=row.user_id,
            questions=row.event_count,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            estimated_cost_usd=float(row.cost_usd),
        )
        for row in top_user_rows
    ]

    top_model_rows = await usage_repository.aggregate_by_model(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
    )
    top_models = [
        TopModelUsageResponse(
            model_name=row.model_name,
            event_count=row.event_count,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            estimated_cost_usd=float(row.cost_usd),
        )
        for row in top_model_rows
    ]

    feature_area_breakdown = await usage_repository.count_events_by_feature_area(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
    )

    avg_latency = total_bucket.average_latency_ms()
    totals = UsageDashboardTotalsResponse(
        questions_asked=total_bucket.questions_asked,
        input_tokens=total_bucket.input_tokens,
        output_tokens=total_bucket.output_tokens,
        estimated_cost_usd=float(total_bucket.estimated_cost_usd),
        active_users=total_bucket.active_users(),
        documents=total_docs,
        indexed_documents=indexed_docs,
        total_chunks=total_chunks,
        indexing_jobs=total_bucket.indexing_jobs,
        failed_indexing_jobs=total_bucket.failed_indexing_jobs,
        evaluation_runs=total_bucket.evaluation_runs,
        agent_runs=total_bucket.agent_runs,
        api_calls=total_bucket.api_calls,
        avg_confidence=total_bucket.average_confidence(),
        avg_latency_ms=avg_latency,
        latency_score=_latency_score_from_average(avg_latency),
    )

    return UsageDashboardResponse(
        organization_id=str(organization_id),
        range=UsageSummaryRange(from_date=resolved_from, to_date=resolved_to),
        granularity=granularity,
        is_cost_estimate=True,
        totals=totals,
        series=series,
        top_users=top_users,
        top_models=top_models,
        feature_area_breakdown=feature_area_breakdown,
    )


@router.get("/usage/export")
async def export_admin_usage(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    export_format: Annotated[UsageExportFormat, Query(alias="format")] = "csv",
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    user_id: UUID | None = None,
    model: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    feature_area: FeatureArea = "all",
    limit: Annotated[int, Query(ge=1, le=50000)] = 10000,
) -> Response:
    organization_id = _organization_id_from_principal(principal)
    resolved_from, resolved_to = _normalize_date_range(from_date=from_date, to_date=to_date)
    from_created_at, to_created_at = _to_datetime_bounds(resolved_from, resolved_to)

    event_type_prefix: str | None = None
    if feature_area != "all":
        event_type_prefix = _FEATURE_AREA_TO_PREFIX.get(feature_area)

    events = await usage_repository.list_usage_events_filtered(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=user_id,
        model_name=model,
        event_type_prefix=event_type_prefix,
    )
    events = events[:limit]

    filename = f"usage-{resolved_from.isoformat()}-{resolved_to.isoformat()}.{export_format}"

    if export_format == "json":
        payload = {
            "organization_id": str(organization_id),
            "exported_at": datetime.now(tz=UTC).isoformat(),
            "is_cost_estimate": True,
            "range": {"from": resolved_from.isoformat(), "to": resolved_to.isoformat()},
            "returned": len(events),
            "max_rows": limit,
            "items": [
                {
                    "id": str(e.id),
                    "created_at": e.created_at.isoformat(),
                    "organization_id": str(e.organization_id),
                    "user_id": str(e.user_id) if e.user_id else None,
                    "event_type": e.event_type,
                    "model_name": e.model_name,
                    "input_tokens": e.input_tokens,
                    "output_tokens": e.output_tokens,
                    "estimated_cost_usd": str(e.cost_usd) if e.cost_usd is not None else None,
                }
                for e in events
            ],
        }
        return Response(
            content=json.dumps(payload, sort_keys=True),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    csv_payload = _serialize_usage_events_csv(events)
    return Response(
        content=csv_payload,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/usage", response_model=UsageSummaryResponse)
async def get_admin_usage_summary(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    granularity: UsageGranularity = "day",
    user_id: UUID | None = None,
) -> UsageSummaryResponse:
    organization_id = _organization_id_from_principal(principal)
    resolved_from, resolved_to = _normalize_date_range(from_date=from_date, to_date=to_date)
    from_created_at, to_created_at = _to_datetime_bounds(resolved_from, resolved_to)

    events = await usage_repository.list_usage_events(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=user_id,
    )
    totals, series = _aggregate_usage(events, granularity=granularity)

    return UsageSummaryResponse(
        organization_id=str(organization_id),
        range=UsageSummaryRange(from_date=resolved_from, to_date=resolved_to),
        granularity=granularity,
        totals=totals,
        series=series,
    )


@router.get("/agent/diagnostics", response_model=AgentDiagnosticsResponse)
async def get_admin_agent_diagnostics(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    granularity: UsageGranularity = "day",
    user_id: UUID | None = None,
) -> AgentDiagnosticsResponse:
    organization_id = _organization_id_from_principal(principal)
    resolved_from, resolved_to = _normalize_date_range(from_date=from_date, to_date=to_date)
    from_created_at, to_created_at = _to_datetime_bounds(resolved_from, resolved_to)

    events = await usage_repository.list_usage_events(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=user_id,
    )
    filtered_events = [event for event in events if event.event_type in AGENT_EVENT_TYPES]
    totals, series, errors_by_code = _aggregate_agent_diagnostics(
        filtered_events, granularity=granularity
    )
    audit_actions = await usage_repository.count_audit_logs_grouped_by_action(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        action_prefix="agent.",
    )

    return AgentDiagnosticsResponse(
        organization_id=str(organization_id),
        range=UsageSummaryRange(from_date=resolved_from, to_date=resolved_to),
        totals=totals,
        series=series,
        errors_by_code=errors_by_code,
        audit_actions=audit_actions,
    )


def _request_id_from_metadata(metadata: dict[str, object]) -> str | None:
    candidate = _metadata_text_value(metadata, "request_id")
    if candidate:
        return candidate
    return None


def _metadata_text_value(metadata: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                return candidate
        elif isinstance(value, (int, float)) and value == value:
            return str(value)
    return None


def _metadata_status_code(metadata: dict[str, object]) -> int | None:
    for key in ("status_code", "http_status", "statusCode"):
        value = metadata.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value == value:
            return int(value)
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed and trimmed.isdigit():
                return int(trimmed)
    return None


def _audit_result_from_metadata(
    metadata: dict[str, object],
) -> Literal["success", "failure", "unknown"]:
    status_code = _metadata_status_code(metadata)
    if status_code is not None:
        if 200 <= status_code < 400:
            return "success"
        if status_code >= 400:
            return "failure"
    result_value = _metadata_text_value(metadata, "result", "outcome")
    if result_value is not None:
        normalized = result_value.lower()
        if normalized in AUDIT_SUCCESS_RESULTS:
            return "success"
        if normalized in AUDIT_FAILURE_RESULTS:
            return "failure"
    return "unknown"


def _normalized_uuid_text(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _to_audit_log_item(log: AuditLog) -> AuditLogListItemResponse:
    raw_metadata = log.metadata_json if isinstance(log.metadata_json, dict) else {}
    metadata = sanitize_metadata(raw_metadata)
    document_id = _metadata_text_value(metadata, "document_id")
    collection_id = _metadata_text_value(metadata, "collection_id")
    if log.resource_type == "document" and log.resource_id is not None:
        document_id = str(log.resource_id)
    if log.resource_type == "collection" and log.resource_id is not None:
        collection_id = str(log.resource_id)

    return AuditLogListItemResponse(
        audit_log_id=str(log.id),
        organization_id=str(log.organization_id),
        user_id=str(log.user_id) if log.user_id else None,
        action=log.action,
        resource_type=log.resource_type,
        resource_id=str(log.resource_id) if log.resource_id else None,
        request_id=_request_id_from_metadata(metadata),
        result=_audit_result_from_metadata(metadata),
        severity=_metadata_text_value(metadata, "severity"),
        ip_address=_metadata_text_value(metadata, "ip_address", "ip"),
        session_id=_metadata_text_value(
            metadata,
            "session_id",
            "auth_session_id",
            "chat_session_id",
        ),
        document_id=_normalized_uuid_text(document_id) or document_id,
        collection_id=_normalized_uuid_text(collection_id) or collection_id,
        metadata=metadata,
        created_at=log.created_at,
    )


@dataclass(frozen=True)
class _AuditFilterState:
    actor_user_id: UUID | None
    system_actor_only: bool
    actor_email: str | None
    entity: str | None
    action: str | None
    resource_id: UUID | None
    request_id: str | None
    session_id: str | None
    ip_address: str | None
    document_id: UUID | None
    collection_id: UUID | None
    result: str | None
    severity: str | None
    search: str | None


def _resolve_audit_filter_state(
    *,
    actor: str | None,
    user_id: UUID | None,
    entity: str | None,
    resource_type: str | None,
    action: str | None,
    resource_id: UUID | None,
    request_id: str | None,
    session_id: str | None,
    ip_address: str | None,
    document_id: UUID | None,
    collection_id: UUID | None,
    result: AuditResultFilter,
    severity: str | None,
    search: str | None,
) -> _AuditFilterState:
    resolved_actor_user_id = user_id
    system_actor_only = False
    actor_email = None
    if actor is not None and user_id is None:
        normalized_actor = actor.strip()
        if normalized_actor:
            if normalized_actor.lower() in {"system", "service"}:
                system_actor_only = True
            else:
                try:
                    resolved_actor_user_id = UUID(normalized_actor)
                except ValueError:
                    actor_email = normalized_actor.lower()

    if entity and resource_type and entity != resource_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="entity and resource_type filters must match when both are provided",
        )

    resolved_entity = entity or resource_type
    resolved_result = result if result != "all" else None
    resolved_severity = severity.strip().lower() if severity and severity.strip() else None
    resolved_search = search.strip().lower() if search and search.strip() else None

    return _AuditFilterState(
        actor_user_id=resolved_actor_user_id,
        system_actor_only=system_actor_only,
        actor_email=actor_email,
        entity=resolved_entity,
        action=action,
        resource_id=resource_id,
        request_id=request_id,
        session_id=session_id,
        ip_address=ip_address,
        document_id=document_id,
        collection_id=collection_id,
        result=resolved_result,
        severity=resolved_severity,
        search=resolved_search,
    )


def _build_audit_export_filename(
    *,
    from_date: date,
    to_date: date,
    export_format: AuditExportFormat,
) -> str:
    return f"audit-logs-{from_date.isoformat()}-{to_date.isoformat()}.{export_format}"


def _serialize_audit_logs_csv(items: list[AuditLogListItemResponse]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "audit_log_id",
            "created_at",
            "organization_id",
            "user_id",
            "action",
            "resource_type",
            "resource_id",
            "request_id",
            "result",
            "severity",
            "ip_address",
            "session_id",
            "document_id",
            "collection_id",
            "metadata_json",
        ],
    )
    writer.writeheader()
    for item in items:
        writer.writerow(
            {
                "audit_log_id": item.audit_log_id,
                "created_at": item.created_at.isoformat(),
                "organization_id": item.organization_id,
                "user_id": item.user_id or "",
                "action": item.action,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id or "",
                "request_id": item.request_id or "",
                "result": item.result,
                "severity": item.severity or "",
                "ip_address": item.ip_address or "",
                "session_id": item.session_id or "",
                "document_id": item.document_id or "",
                "collection_id": item.collection_id or "",
                "metadata_json": json.dumps(item.metadata, sort_keys=True),
            }
        )
    return output.getvalue()


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_admin_audit_logs(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    organization_filter_id: Annotated[UUID | None, Query(alias="organization_id")] = None,
    actor: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    user_id: UUID | None = None,
    action: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    entity: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resource_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resource_id: UUID | None = None,
    document_id: UUID | None = None,
    collection_id: UUID | None = None,
    request_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    ip_address: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    result: AuditResultFilter = "all",
    severity: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> AuditLogListResponse:
    organization_id = _organization_id_from_principal(principal)
    if organization_filter_id is not None and organization_filter_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-organization audit access is not allowed",
        )
    resolved_from, resolved_to = _normalize_date_range(from_date=from_date, to_date=to_date)
    from_created_at, to_created_at = _to_datetime_bounds(resolved_from, resolved_to)
    filters = _resolve_audit_filter_state(
        actor=actor,
        user_id=user_id,
        entity=entity,
        resource_type=resource_type,
        action=action,
        resource_id=resource_id,
        request_id=request_id,
        session_id=session_id,
        ip_address=ip_address,
        document_id=document_id,
        collection_id=collection_id,
        result=result,
        severity=severity,
        search=search,
    )

    total = await usage_repository.count_audit_logs(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=filters.actor_user_id,
        system_actor_only=filters.system_actor_only,
        actor_email=filters.actor_email,
        action=filters.action,
        resource_type=filters.entity,
        resource_id=filters.resource_id,
        request_id=filters.request_id,
        session_id=filters.session_id,
        ip_address=filters.ip_address,
        document_id=filters.document_id,
        collection_id=filters.collection_id,
        result=filters.result,
        severity=filters.severity,
        search=filters.search,
    )

    logs = await usage_repository.list_audit_logs(
        db_session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=filters.actor_user_id,
        system_actor_only=filters.system_actor_only,
        actor_email=filters.actor_email,
        action=filters.action,
        resource_type=filters.entity,
        resource_id=filters.resource_id,
        request_id=filters.request_id,
        session_id=filters.session_id,
        ip_address=filters.ip_address,
        document_id=filters.document_id,
        collection_id=filters.collection_id,
        result=filters.result,
        severity=filters.severity,
        search=filters.search,
    )

    items = [_to_audit_log_item(log) for log in logs]
    return AuditLogListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        range=UsageSummaryRange(from_date=resolved_from, to_date=resolved_to),
    )


@router.get("/audit-logs/export")
async def export_admin_audit_logs(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    export_format: Annotated[AuditExportFormat, Query(alias="format")] = "csv",
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    organization_filter_id: Annotated[UUID | None, Query(alias="organization_id")] = None,
    actor: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    user_id: UUID | None = None,
    action: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    entity: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resource_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resource_id: UUID | None = None,
    document_id: UUID | None = None,
    collection_id: UUID | None = None,
    request_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    session_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    ip_address: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    result: AuditResultFilter = "all",
    severity: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=10000)] = 5000,
) -> Response:
    organization_id = _organization_id_from_principal(principal)
    if organization_filter_id is not None and organization_filter_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-organization audit access is not allowed",
        )

    resolved_from, resolved_to = _normalize_date_range(from_date=from_date, to_date=to_date)
    from_created_at, to_created_at = _to_datetime_bounds(resolved_from, resolved_to)
    filters = _resolve_audit_filter_state(
        actor=actor,
        user_id=user_id,
        entity=entity,
        resource_type=resource_type,
        action=action,
        resource_id=resource_id,
        request_id=request_id,
        session_id=session_id,
        ip_address=ip_address,
        document_id=document_id,
        collection_id=collection_id,
        result=result,
        severity=severity,
        search=search,
    )

    logs = await usage_repository.list_audit_logs(
        db_session,
        organization_id=organization_id,
        limit=limit,
        offset=0,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=filters.actor_user_id,
        system_actor_only=filters.system_actor_only,
        actor_email=filters.actor_email,
        action=filters.action,
        resource_type=filters.entity,
        resource_id=filters.resource_id,
        request_id=filters.request_id,
        session_id=filters.session_id,
        ip_address=filters.ip_address,
        document_id=filters.document_id,
        collection_id=filters.collection_id,
        result=filters.result,
        severity=filters.severity,
        search=filters.search,
    )
    items = [_to_audit_log_item(log) for log in logs]
    filename = _build_audit_export_filename(
        from_date=resolved_from, to_date=resolved_to, export_format=export_format
    )

    if export_format == "json":
        payload = {
            "organization_id": str(organization_id),
            "exported_at": datetime.now(tz=UTC).isoformat(),
            "range": {
                "from": resolved_from.isoformat(),
                "to": resolved_to.isoformat(),
            },
            "filters": {
                "actor": actor,
                "user_id": str(user_id) if user_id is not None else None,
                "action": action,
                "entity": entity or resource_type,
                "resource_id": str(resource_id) if resource_id is not None else None,
                "document_id": str(document_id) if document_id is not None else None,
                "collection_id": str(collection_id) if collection_id is not None else None,
                "request_id": request_id,
                "session_id": session_id,
                "ip_address": ip_address,
                "result": result,
                "severity": severity,
                "search": search,
            },
            "returned": len(items),
            "max_rows": limit,
            "items": [item.model_dump(mode="json") for item in items],
        }
        return Response(
            content=json.dumps(payload, sort_keys=True),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    csv_payload = _serialize_audit_logs_csv(items)
    return Response(
        content=csv_payload,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
