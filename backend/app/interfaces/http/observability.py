from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.schemas.observability import (
    ApiMetrics,
    IndexingMetrics,
    LlmMetrics,
    LlmModelSummary,
    ObservabilityRange,
    ObservabilitySnapshot,
    StorageMetrics,
)
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.usage import AuditLog, UsageEvent
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/observability", tags=["admin-observability"])

_DEFAULT_RANGE_DAYS = 30
_MAX_RANGE_DAYS = 90
_TOP_MODELS_LIMIT = 10

_AUDIT_FAILURE_RESULTS = frozenset({"failed", "failure", "error", "denied", "rejected"})

_PENDING_DOC_STATUSES = ("uploaded", "processing")
_FAILED_DOC_STATUSES = ("failed", "quarantined", "blocked")
_INDEXED_DOC_STATUS = "indexed"
_EXCLUDED_DOC_STATUSES = ("deleted",)

_LLM_EVENT_TYPE_PREFIX = "chat"
_PIPELINE_EVENT_TYPE_PREFIX = "pipeline"


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


def _extract_float(metadata: dict, *keys: str) -> float | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            candidate = float(value)
            if candidate == candidate:
                return candidate
    return None


def _has_llm_error(metadata: dict) -> bool:
    error_value = metadata.get("error")
    if error_value is not None and error_value is not False and error_value != "":
        return True
    status_value = metadata.get("status")
    if isinstance(status_value, str) and status_value.lower() in {"error", "failed", "failure"}:
        return True
    return False


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * pct
    lower = int(idx)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = idx - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


async def _build_api_metrics(
    db: AsyncSession,
    *,
    organization_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
) -> ApiMetrics:
    stmt = select(AuditLog).where(
        AuditLog.organization_id == organization_id,
        AuditLog.created_at >= from_dt,
        AuditLog.created_at <= to_dt,
    )
    rows = list((await db.execute(stmt)).scalars().all())

    total = len(rows)
    failed = 0
    latency_values: list[float] = []

    for row in rows:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        result = (
            (row.metadata_json or {}).get("result") if isinstance(row.metadata_json, dict) else None
        )
        if isinstance(result, str) and result.lower() in _AUDIT_FAILURE_RESULTS:
            failed += 1
        lat = _extract_float(metadata, "latency_ms", "duration_ms", "answer_latency_ms")
        if lat is not None and lat >= 0:
            latency_values.append(lat)

    error_rate = (failed / total) if total > 0 else None
    avg_lat = (sum(latency_values) / len(latency_values)) if latency_values else None
    p95_lat = _percentile(latency_values, 0.95)

    return ApiMetrics(
        total_requests=total,
        failed_requests=failed,
        error_rate=error_rate,
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        telemetry_missing=total == 0,
    )


async def _build_llm_metrics(
    db: AsyncSession,
    *,
    organization_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
) -> LlmMetrics:
    stmt = select(UsageEvent).where(
        UsageEvent.organization_id == organization_id,
        UsageEvent.created_at >= from_dt,
        UsageEvent.created_at <= to_dt,
        UsageEvent.model_name.is_not(None),
    )
    rows = list((await db.execute(stmt)).scalars().all())

    total = len(rows)
    failed = 0
    latency_values: list[float] = []
    model_counts: dict[str, int] = {}
    model_errors: dict[str, int] = {}

    for row in rows:
        model = row.model_name or "unknown"
        model_counts[model] = model_counts.get(model, 0) + 1
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        if _has_llm_error(metadata):
            failed += 1
            model_errors[model] = model_errors.get(model, 0) + 1
        lat = _extract_float(metadata, "latency_ms", "answer_latency_ms", "duration_ms")
        if lat is not None and lat >= 0:
            latency_values.append(lat)

    top_models = sorted(model_counts.items(), key=lambda kv: kv[1], reverse=True)[
        :_TOP_MODELS_LIMIT
    ]
    top_model_summaries = [
        LlmModelSummary(
            model_name=name,
            event_count=count,
            error_count=model_errors.get(name, 0),
        )
        for name, count in top_models
    ]

    error_rate = (failed / total) if total > 0 else None
    avg_lat = (sum(latency_values) / len(latency_values)) if latency_values else None

    return LlmMetrics(
        total_events=total,
        failed_events=failed,
        error_rate=error_rate,
        avg_latency_ms=avg_lat,
        top_models=top_model_summaries,
        telemetry_missing=total == 0,
    )


async def _build_indexing_metrics(
    db: AsyncSession,
    *,
    organization_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
) -> IndexingMetrics:
    stmt = select(UsageEvent).where(
        UsageEvent.organization_id == organization_id,
        UsageEvent.created_at >= from_dt,
        UsageEvent.created_at <= to_dt,
        UsageEvent.event_type.startswith(_PIPELINE_EVENT_TYPE_PREFIX),
    )
    rows = list((await db.execute(stmt)).scalars().all())

    total = len(rows)
    succeeded = 0
    failed = 0
    in_progress = 0

    for row in rows:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        pipeline_status = metadata.get("status")
        if isinstance(pipeline_status, str):
            normalized = pipeline_status.lower()
            if normalized in {"completed", "success", "succeeded", "indexed"}:
                succeeded += 1
            elif normalized in {"failed", "failure", "error"}:
                failed += 1
            elif normalized in {"processing", "running", "in_progress", "queued"}:
                in_progress += 1
            else:
                succeeded += 1
        else:
            succeeded += 1

    success_rate = (succeeded / total) if total > 0 else None

    return IndexingMetrics(
        total_jobs=total,
        succeeded_jobs=succeeded,
        failed_jobs=failed,
        in_progress_jobs=in_progress,
        success_rate=success_rate,
        telemetry_missing=total == 0,
    )


async def _build_storage_metrics(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> StorageMetrics:
    total_stmt = select(func.count(Document.id)).where(
        Document.organization_id == organization_id,
        Document.status.not_in(_EXCLUDED_DOC_STATUSES),
    )
    indexed_stmt = select(func.count(Document.id)).where(
        Document.organization_id == organization_id,
        Document.status == _INDEXED_DOC_STATUS,
    )
    failed_stmt = select(func.count(Document.id)).where(
        Document.organization_id == organization_id,
        Document.status.in_(_FAILED_DOC_STATUSES),
    )
    pending_stmt = select(func.count(Document.id)).where(
        Document.organization_id == organization_id,
        Document.status.in_(_PENDING_DOC_STATUSES),
    )
    chunks_stmt = select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
        Document.organization_id == organization_id,
        Document.status == _INDEXED_DOC_STATUS,
    )

    total_docs = int((await db.execute(total_stmt)).scalar_one() or 0)
    indexed_docs = int((await db.execute(indexed_stmt)).scalar_one() or 0)
    failed_docs = int((await db.execute(failed_stmt)).scalar_one() or 0)
    pending_docs = int((await db.execute(pending_stmt)).scalar_one() or 0)
    total_chunks = int((await db.execute(chunks_stmt)).scalar_one() or 0)

    return StorageMetrics(
        total_documents=total_docs,
        indexed_documents=indexed_docs,
        failed_documents=failed_docs,
        pending_documents=pending_docs,
        total_chunks=total_chunks,
    )


@router.get("", response_model=ObservabilitySnapshot)
async def get_observability_snapshot(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> ObservabilitySnapshot:
    organization_id = _organization_id(principal)
    resolved_from, resolved_to = _resolve_date_range(from_date, to_date)
    from_dt, to_dt = _to_datetime_bounds(resolved_from, resolved_to)

    api_metrics = await _build_api_metrics(
        db, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
    )
    llm_metrics = await _build_llm_metrics(
        db, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
    )
    indexing_metrics = await _build_indexing_metrics(
        db, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt
    )
    storage_metrics = await _build_storage_metrics(db, organization_id=organization_id)

    return ObservabilitySnapshot(
        organization_id=str(organization_id),
        range=ObservabilityRange(from_date=resolved_from, to_date=resolved_to),
        generated_at=datetime.now(tz=UTC),
        api_metrics=api_metrics,
        llm_metrics=llm_metrics,
        indexing_metrics=indexing_metrics,
        storage_metrics=storage_metrics,
    )
