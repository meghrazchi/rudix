"""Admin trust analytics endpoint (F317).

GET /admin/trust-analytics — returns aggregated trust panel metrics:
  - Trust score distribution (high/medium/low/warning/not_found)
  - Warning type breakdown (stale, conflict, OCR, extraction)
  - Not-found rate and average confidence/citation-support scores
  - Daily trends for time-range charts
  - Langfuse trace-link availability

No raw question/answer text or document IDs are exposed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.langfuse_tracer import check_langfuse_health
from app.db.session import get_db_session
from app.domains.admin.schemas.trust_analytics import (
    LangfuseIntegrationStatus,
    TrustAnalyticsDateRange,
    TrustAnalyticsResponse,
    TrustDistribution,
    TrustTrendPoint,
    WarningBreakdown,
)
from app.models.enums import OrganizationRole
from app.models.usage import UsageEvent
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/trust-analytics", tags=["admin-trust-analytics"])

_DEFAULT_RANGE_DAYS = 30
_MAX_RANGE_DAYS = 90
_TRUST_EVENT_TYPE = "trust.answer_metrics"


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


def _safe_float(meta: dict, key: str) -> float | None:
    val = meta.get(key)
    if isinstance(val, (int, float)) and val == val:
        return float(val)
    return None


def _safe_bool(meta: dict, key: str) -> bool:
    val = meta.get(key)
    return bool(val) if val is not None else False


def _safe_int(meta: dict, key: str) -> int:
    val = meta.get(key)
    return int(val) if isinstance(val, (int, float)) else 0


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _safe_pct(count: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(count / total, 4)


def _build_distribution(events: list[UsageEvent]) -> TrustDistribution:
    high = medium = low = warning = not_found = 0
    for event in events:
        meta = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        level = meta.get("trust_level")
        if level == "high":
            high += 1
        elif level == "medium":
            medium += 1
        elif level == "low":
            low += 1
        elif level == "warning":
            warning += 1
        elif level == "not_found":
            not_found += 1
        else:
            low += 1
    total = len(events)
    return TrustDistribution(
        high_count=high,
        medium_count=medium,
        low_count=low,
        warning_count=warning,
        not_found_count=not_found,
        high_pct=_safe_pct(high, total),
        medium_pct=_safe_pct(medium, total),
        low_pct=_safe_pct(low, total),
        warning_pct=_safe_pct(warning, total),
        not_found_pct=_safe_pct(not_found, total),
    )


def _build_warnings(events: list[UsageEvent]) -> WarningBreakdown:
    stale = conflict = ocr = extraction = processing = evidence = citation_fail = 0
    for event in events:
        meta = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        if _safe_bool(meta, "stale_source_warning"):
            stale += 1
        if _safe_bool(meta, "conflict_detected"):
            conflict += 1
        if _safe_bool(meta, "ocr_warning"):
            ocr += 1
        if _safe_bool(meta, "extraction_warning"):
            extraction += 1
        if _safe_bool(meta, "processing_warning"):
            processing += 1
        if _safe_bool(meta, "evidence_quality_warning"):
            evidence += 1
        if _safe_bool(meta, "citation_validation_failed"):
            citation_fail += 1
    return WarningBreakdown(
        stale_source_count=stale,
        conflict_count=conflict,
        ocr_count=ocr,
        extraction_count=extraction,
        processing_count=processing,
        evidence_quality_count=evidence,
        citation_validation_failed_count=citation_fail,
    )


def _build_daily_trends(
    events: list[UsageEvent],
    from_date: date,
    to_date: date,
) -> list[TrustTrendPoint]:
    # Bucket events by date
    by_date: dict[date, list[dict]] = defaultdict(list)
    for event in events:
        event_date = event.created_at.date() if event.created_at else None
        if event_date is None:
            continue
        meta = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        by_date[event_date].append(meta)

    trends: list[TrustTrendPoint] = []
    current = from_date
    while current <= to_date:
        day_events = by_date.get(current, [])
        count = len(day_events)
        not_found_count = sum(1 for m in day_events if _safe_bool(m, "not_found"))
        conf_scores = [
            v for m in day_events if (v := _safe_float(m, "confidence_score")) is not None
        ]
        cit_scores = [
            v for m in day_events if (v := _safe_float(m, "citation_support_score")) is not None
        ]
        high_count = sum(1 for m in day_events if m.get("trust_level") == "high")
        low_count = sum(
            1 for m in day_events if m.get("trust_level") in ("low", "warning", "not_found")
        )
        trends.append(
            TrustTrendPoint(
                date=current,
                answer_count=count,
                not_found_count=not_found_count,
                not_found_rate=_safe_pct(not_found_count, count),
                avg_confidence_score=_mean_or_none(conf_scores),
                avg_citation_support_score=_mean_or_none(cit_scores),
                high_trust_count=high_count,
                low_trust_count=low_count,
            )
        )
        current += timedelta(days=1)
    return trends


@router.get("", response_model=TrustAnalyticsResponse)
async def get_trust_analytics(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> TrustAnalyticsResponse:
    """Return aggregated trust panel metrics for the requesting organization.

    No raw question/answer text or document IDs are included in the response.
    """
    org_id = _organization_id(principal)
    resolved_from, resolved_to = _resolve_date_range(from_date, to_date)
    from_dt, to_dt = _to_datetime_bounds(resolved_from, resolved_to)

    stmt = select(UsageEvent).where(
        UsageEvent.organization_id == org_id,
        UsageEvent.event_type == _TRUST_EVENT_TYPE,
        UsageEvent.created_at >= from_dt,
        UsageEvent.created_at <= to_dt,
    )
    events = list((await db.execute(stmt)).scalars().all())

    total = len(events)
    if total == 0:
        langfuse_health = await check_langfuse_health()
        return TrustAnalyticsResponse(
            organization_id=str(org_id),
            range=TrustAnalyticsDateRange.model_validate(
                {"from": resolved_from, "to": resolved_to}
            ),
            generated_at=datetime.now(tz=UTC),
            total_answers=0,
            trust_distribution=TrustDistribution(),
            warnings=WarningBreakdown(),
            daily_trends=_build_daily_trends([], resolved_from, resolved_to),
            langfuse=LangfuseIntegrationStatus(
                enabled=bool(langfuse_health.get("enabled")),
                traces_linked_count=0,
            ),
            telemetry_missing=True,
        )

    # Aggregate scalars
    not_found_count = 0
    conflict_count = 0
    unsupported_removed = 0
    conf_scores: list[float] = []
    cit_support_scores: list[float] = []
    verif_support_scores: list[float] = []
    langfuse_linked = 0

    for event in events:
        meta = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        if _safe_bool(meta, "not_found"):
            not_found_count += 1
        if _safe_bool(meta, "conflict_detected"):
            conflict_count += 1
        unsupported_removed += _safe_int(meta, "unsupported_claims_removed")
        if (v := _safe_float(meta, "confidence_score")) is not None:
            conf_scores.append(v)
        if (v := _safe_float(meta, "citation_support_score")) is not None:
            cit_support_scores.append(v)
        if (v := _safe_float(meta, "verification_support_score")) is not None:
            verif_support_scores.append(v)
        if meta.get("langfuse_trace_id"):
            langfuse_linked += 1

    langfuse_health = await check_langfuse_health()

    return TrustAnalyticsResponse(
        organization_id=str(org_id),
        range=TrustAnalyticsDateRange.model_validate({"from": resolved_from, "to": resolved_to}),
        generated_at=datetime.now(tz=UTC),
        total_answers=total,
        not_found_rate=_safe_pct(not_found_count, total),
        avg_confidence_score=_mean_or_none(conf_scores),
        avg_citation_support_score=_mean_or_none(cit_support_scores),
        avg_verification_support_score=_mean_or_none(verif_support_scores),
        unsupported_claims_removed_total=unsupported_removed,
        conflict_detection_rate=_safe_pct(conflict_count, total),
        trust_distribution=_build_distribution(events),
        warnings=_build_warnings(events),
        daily_trends=_build_daily_trends(events, resolved_from, resolved_to),
        langfuse=LangfuseIntegrationStatus(
            enabled=bool(langfuse_health.get("enabled")),
            traces_linked_count=langfuse_linked,
        ),
        telemetry_missing=False,
    )
