"""Admin endpoint for graph observability metrics and alerting (F291).

GET /admin/graph/observability — returns a GraphObservabilitySnapshot covering
extraction health, entity/relation quality, GraphRAG query performance, and
computed alert items based on configurable thresholds.

Auth: owner/admin only.
All data is org-scoped.  Neo4j outage degrades gracefully (telemetry_missing).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.clients.neo4j_client import check_neo4j_health, get_driver
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.graph.repositories.metrics_repository import (
    get_entity_metrics,
    get_extraction_metrics,
    get_query_metrics,
    get_relation_metrics,
    get_trend_metrics,
)
from app.domains.graph.schemas.observability import (
    GraphAlertItem,
    GraphAlertLevel,
    GraphAlertThresholds,
    GraphObservabilityRange,
    GraphObservabilitySnapshot,
)
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/graph/observability", tags=["admin-graph-observability"])

_DEFAULT_RANGE_DAYS = 30
_MAX_RANGE_DAYS = 90


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


def _build_thresholds() -> GraphAlertThresholds:
    return GraphAlertThresholds(
        extraction_failure_rate_max=settings.graph_alert_extraction_failure_rate_max,
        query_failure_rate_max=settings.graph_alert_query_failure_rate_max,
        graphrag_fallback_rate_max=settings.graph_alert_graphrag_fallback_rate_max,
        low_confidence_entity_rate_max=settings.graph_alert_low_confidence_entity_rate_max,
        query_latency_ms_max=settings.graph_alert_query_latency_ms_max,
    )


def _compute_alerts(
    snapshot: GraphObservabilitySnapshot,
    thresholds: GraphAlertThresholds,
) -> list[GraphAlertItem]:
    alerts: list[GraphAlertItem] = []

    if not snapshot.neo4j_reachable and snapshot.graph_enabled:
        alerts.append(
            GraphAlertItem(
                level="critical",
                metric="neo4j_reachable",
                message="Neo4j is configured but unreachable. Graph extraction and GraphRAG are unavailable.",
            )
        )

    extraction = snapshot.extraction
    if extraction.success_rate is not None:
        failure_rate = 1.0 - extraction.success_rate
        if failure_rate >= thresholds.extraction_failure_rate_max:
            alert_level: GraphAlertLevel = "critical" if failure_rate >= 0.5 else "warning"
            alerts.append(
                GraphAlertItem(
                    level=alert_level,
                    metric="extraction_failure_rate",
                    message=(
                        f"Graph extraction failure rate is {failure_rate:.0%}, "
                        f"exceeding the {thresholds.extraction_failure_rate_max:.0%} threshold."
                    ),
                )
            )

    queries = snapshot.queries
    if (
        queries.failure_rate is not None
        and queries.failure_rate >= thresholds.query_failure_rate_max
    ):
        alerts.append(
            GraphAlertItem(
                level="warning",
                metric="graphrag_failure_rate",
                message=(
                    f"GraphRAG query failure rate is {queries.failure_rate:.0%}, "
                    f"exceeding the {thresholds.query_failure_rate_max:.0%} threshold."
                ),
            )
        )

    if (
        queries.fallback_rate is not None
        and queries.fallback_rate >= thresholds.graphrag_fallback_rate_max
    ):
        alerts.append(
            GraphAlertItem(
                level="warning",
                metric="graphrag_fallback_rate",
                message=(
                    f"GraphRAG is falling back to standard RAG {queries.fallback_rate:.0%} of the time, "
                    f"exceeding the {thresholds.graphrag_fallback_rate_max:.0%} threshold."
                ),
            )
        )

    if (
        queries.p95_latency_ms is not None
        and queries.p95_latency_ms >= thresholds.query_latency_ms_max
    ):
        alerts.append(
            GraphAlertItem(
                level="warning",
                metric="graphrag_latency_ms_p95",
                message=(
                    f"GraphRAG p95 latency is {queries.p95_latency_ms:.0f} ms, "
                    f"exceeding the {thresholds.query_latency_ms_max:.0f} ms threshold."
                ),
            )
        )

    entities = snapshot.entities
    if entities.total_entities > 0:
        low_conf_rate = entities.low_confidence_count / entities.total_entities
        if low_conf_rate >= thresholds.low_confidence_entity_rate_max:
            alerts.append(
                GraphAlertItem(
                    level="warning",
                    metric="low_confidence_entity_rate",
                    message=(
                        f"{low_conf_rate:.0%} of entities have confidence below 0.5, "
                        f"exceeding the {thresholds.low_confidence_entity_rate_max:.0%} threshold. "
                        "Review extraction quality or lower the confidence threshold."
                    ),
                )
            )

    return alerts


@router.get("", response_model=GraphObservabilitySnapshot)
async def get_graph_observability(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> GraphObservabilitySnapshot:
    """Return graph observability snapshot including extraction health, entity/relation
    quality metrics, GraphRAG query performance, and computed alert items.

    Neo4j entity/relation metrics degrade gracefully when the graph is unavailable.
    """
    organization_id = _organization_id(principal)
    resolved_from, resolved_to = _resolve_date_range(from_date, to_date)
    from_dt, to_dt = _to_datetime_bounds(resolved_from, resolved_to)

    graph_enabled = settings.enterprise_graph_enabled
    neo4j_reachable = False
    if graph_enabled and get_driver() is not None:
        neo4j_reachable = await check_neo4j_health()

    extraction, entities, relations, queries = await _gather_metrics(
        db=db,
        organization_id=organization_id,
        from_dt=from_dt,
        to_dt=to_dt,
    )
    trends = await get_trend_metrics(
        db=db,
        organization_id=organization_id,
        from_dt=from_dt,
        to_dt=to_dt,
    )

    thresholds = _build_thresholds()

    snapshot = GraphObservabilitySnapshot(
        organization_id=str(organization_id),
        range=GraphObservabilityRange(**{"from": resolved_from, "to": resolved_to}),
        generated_at=datetime.now(tz=UTC),
        graph_enabled=graph_enabled,
        neo4j_reachable=neo4j_reachable,
        extraction=extraction,
        entities=entities,
        relations=relations,
        queries=queries,
        thresholds=thresholds,
        alerts=[],
        trends=trends,
    )
    snapshot.alerts = _compute_alerts(snapshot, thresholds)
    return snapshot


async def _gather_metrics(
    *,
    db: AsyncSession,
    organization_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
) -> tuple:
    """Run PostgreSQL and Neo4j metric queries concurrently."""
    import asyncio

    extraction_task = asyncio.create_task(
        get_extraction_metrics(db, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt)
    )
    entities_task = asyncio.create_task(get_entity_metrics(organization_id=organization_id))
    relations_task = asyncio.create_task(get_relation_metrics(organization_id=organization_id))
    queries_task = asyncio.create_task(
        get_query_metrics(db, organization_id=organization_id, from_dt=from_dt, to_dt=to_dt)
    )

    extraction = await extraction_task
    entities = await entities_task
    relations = await relations_task
    queries = await queries_task
    return extraction, entities, relations, queries
