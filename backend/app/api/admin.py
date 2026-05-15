from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.models.enums import OrganizationRole
from app.models.usage import UsageEvent
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.repositories.usage import UsageRepository
from app.schemas.admin import (
    AuditLogListItemResponse,
    AuditLogListResponse,
    UsageGranularity,
    UsageSummaryPointResponse,
    UsageSummaryRange,
    UsageSummaryResponse,
    UsageSummaryTotalsResponse,
)

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

    series = [
        UsageSummaryPointResponse(
            period_start=bucket.period_start,
            period_end=bucket.period_end,
            input_tokens=bucket.input_tokens,
            output_tokens=bucket.output_tokens,
            cost_usd=float(bucket.cost_usd),
            event_count=bucket.event_count,
            avg_confidence=bucket.average_confidence(),
            avg_latency_ms=bucket.average_latency_ms(),
        )
        for bucket_start, bucket in sorted(buckets.items(), key=lambda item: item[0])
    ]

    totals = UsageSummaryTotalsResponse(
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        cost_usd=float(total.cost_usd),
        event_count=total.event_count,
        avg_confidence=total.average_confidence(),
        avg_latency_ms=total.average_latency_ms(),
    )

    return totals, series


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


def _request_id_from_metadata(metadata: dict[str, object]) -> str | None:
    candidate = metadata.get("request_id")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


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
    user_id: UUID | None = None,
    action: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    resource_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> AuditLogListResponse:
    organization_id = _organization_id_from_principal(principal)
    resolved_from, resolved_to = _normalize_date_range(from_date=from_date, to_date=to_date)
    from_created_at, to_created_at = _to_datetime_bounds(resolved_from, resolved_to)

    total = await usage_repository.count_audit_logs(
        db_session,
        organization_id=organization_id,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
    )

    logs = await usage_repository.list_audit_logs(
        db_session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
        from_created_at=from_created_at,
        to_created_at=to_created_at,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
    )

    items = []
    for log in logs:
        metadata = log.metadata_json if isinstance(log.metadata_json, dict) else {}
        items.append(
            AuditLogListItemResponse(
                audit_log_id=str(log.id),
                organization_id=str(log.organization_id),
                user_id=str(log.user_id) if log.user_id else None,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=str(log.resource_id) if log.resource_id else None,
                request_id=_request_id_from_metadata(metadata),
                metadata=metadata,
                created_at=log.created_at,
            )
        )

    return AuditLogListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        range=UsageSummaryRange(from_date=resolved_from, to_date=resolved_to),
    )
