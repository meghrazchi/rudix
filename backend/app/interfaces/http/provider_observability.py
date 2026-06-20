"""Admin HTTP endpoint for provider-level observability (F228).

Endpoint:
  GET /admin/provider-observability — per-provider health cards with latency,
      failure rate, retry rate, timeout rate, fallback count, and SLO
      suggestions. Only metadata is exposed; never prompt text or context.

Auth: owner/admin only. Organization-scoped.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.schemas.provider_observability import (
    ProviderHealthCard,
    ProviderObservabilityRange,
    ProviderObservabilitySnapshot,
    SloSuggestion,
)
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/provider-observability", tags=["admin-provider-observability"])

_DEFAULT_RANGE_DAYS = 30
_MAX_RANGE_DAYS = 90

_usage_repo = UsageRepository()

# SLO thresholds used to generate suggestions
_SLO_FAILURE_RATE_WARN = 0.05  # 5 %
_SLO_TIMEOUT_RATE_WARN = 0.02  # 2 %
_SLO_FALLBACK_RATE_WARN = 0.10  # 10 %
_SLO_LATENCY_WARN_MS = 5_000.0  # 5 s avg latency
_SLO_P95_LATENCY_WARN_MS = 10_000.0  # 10 s p95 latency


def _resolve_date_range(from_date: date | None, to_date: date | None) -> tuple[date, date]:
    today = datetime.now(tz=UTC).date()
    resolved_to = to_date or today
    resolved_from = from_date or (resolved_to - timedelta(days=_DEFAULT_RANGE_DAYS - 1))
    if resolved_from > resolved_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from must be less than or equal to to",
        )
    if (resolved_to - resolved_from).days + 1 > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date range exceeds maximum of {_MAX_RANGE_DAYS} days",
        )
    return resolved_from, resolved_to


def _to_datetime_bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(from_date, time.min, tzinfo=UTC),
        datetime.combine(to_date, time.max, tzinfo=UTC),
    )


def _organization_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid organization context",
        ) from exc


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * pct
    lower = int(idx)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = idx - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


def _build_slo_suggestions(
    failure_rate: float | None,
    timeout_rate: float | None,
    fallback_rate: float | None,
    avg_latency_ms: float | None,
    p95_latency_ms: float | None,
) -> list[SloSuggestion]:
    suggestions: list[SloSuggestion] = []

    if failure_rate is not None and failure_rate > _SLO_FAILURE_RATE_WARN:
        suggestions.append(
            SloSuggestion(
                metric="failure_rate",
                current_value=round(failure_rate, 4),
                suggested_threshold=_SLO_FAILURE_RATE_WARN,
                unit="ratio",
                rationale="Failure rate exceeds 5 %. Investigate error codes and consider "
                "enabling a fallback provider.",
            )
        )
    if timeout_rate is not None and timeout_rate > _SLO_TIMEOUT_RATE_WARN:
        suggestions.append(
            SloSuggestion(
                metric="timeout_rate",
                current_value=round(timeout_rate, 4),
                suggested_threshold=_SLO_TIMEOUT_RATE_WARN,
                unit="ratio",
                rationale="Timeout rate exceeds 2 %. Consider increasing the provider "
                "timeout_seconds or reducing average context length.",
            )
        )
    if fallback_rate is not None and fallback_rate > _SLO_FALLBACK_RATE_WARN:
        suggestions.append(
            SloSuggestion(
                metric="fallback_rate",
                current_value=round(fallback_rate, 4),
                suggested_threshold=_SLO_FALLBACK_RATE_WARN,
                unit="ratio",
                rationale="Fallback rate exceeds 10 %. The primary provider may be unstable. "
                "Review provider health and quota limits.",
            )
        )
    if avg_latency_ms is not None and avg_latency_ms > _SLO_LATENCY_WARN_MS:
        suggestions.append(
            SloSuggestion(
                metric="avg_latency_ms",
                current_value=round(avg_latency_ms, 1),
                suggested_threshold=_SLO_LATENCY_WARN_MS,
                unit="ms",
                rationale="Average latency exceeds 5 s. Consider a faster model, reduced "
                "max_tokens, or a local provider for low-latency workloads.",
            )
        )
    if p95_latency_ms is not None and p95_latency_ms > _SLO_P95_LATENCY_WARN_MS:
        suggestions.append(
            SloSuggestion(
                metric="p95_latency_ms",
                current_value=round(p95_latency_ms, 1),
                suggested_threshold=_SLO_P95_LATENCY_WARN_MS,
                unit="ms",
                rationale="P95 latency exceeds 10 s. Tail latency may impact user experience. "
                "Consider timeout tuning or request-size caps.",
            )
        )
    return suggestions


def _build_provider_card(agg: UsageRepository._ProviderAggRow) -> ProviderHealthCard:
    total = agg.total_events
    failure_rate = (agg.failed_events / total) if total > 0 else None
    timeout_rate = (agg.timed_out_events / total) if total > 0 else None
    fallback_rate = (agg.fallback_events / total) if total > 0 else None
    retry_rate = (agg.retry_events / total) if total > 0 else None
    avg_retry = (agg.total_retry_count / agg.retry_events) if agg.retry_events > 0 else None
    avg_lat = sum(agg.latency_values) / len(agg.latency_values) if agg.latency_values else None
    p95_lat = _percentile(agg.latency_values, 0.95)

    slo_suggestions = _build_slo_suggestions(
        failure_rate=failure_rate,
        timeout_rate=timeout_rate,
        fallback_rate=fallback_rate,
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
    )

    return ProviderHealthCard(
        provider_key=agg.provider_key,
        total_events=total,
        failed_events=agg.failed_events,
        failure_rate=failure_rate,
        timed_out_events=agg.timed_out_events,
        timeout_rate=timeout_rate,
        fallback_events=agg.fallback_events,
        fallback_rate=fallback_rate,
        retry_events=agg.retry_events,
        retry_rate=retry_rate,
        avg_retry_count=avg_retry,
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        slo_suggestions=slo_suggestions,
        telemetry_missing=False,
    )


@router.get("", response_model=ProviderObservabilitySnapshot)
async def get_provider_observability_snapshot(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> ProviderObservabilitySnapshot:
    """Return per-provider health cards for the organization.

    Aggregates usage events by provider_key. Only events emitted after the
    F228 migration carry provider metadata; older events are excluded.
    Never exposes prompt text, context, answers, or secrets.
    Auth: owner/admin only.
    """
    organization_id = _organization_id(principal)
    resolved_from, resolved_to = _resolve_date_range(from_date, to_date)
    from_dt, to_dt = _to_datetime_bounds(resolved_from, resolved_to)

    agg_rows = await _usage_repo.aggregate_by_provider(
        db,
        organization_id=organization_id,
        from_created_at=from_dt,
        to_created_at=to_dt,
    )

    cards = [_build_provider_card(row) for row in agg_rows]
    cards.sort(key=lambda c: c.total_events, reverse=True)

    return ProviderObservabilitySnapshot(
        organization_id=str(organization_id),
        range=ProviderObservabilityRange(**{"from": resolved_from, "to": resolved_to}),
        generated_at=datetime.now(tz=UTC),
        providers=cards,
        telemetry_missing=len(cards) == 0,
    )
