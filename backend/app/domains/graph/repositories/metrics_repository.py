"""Graph metrics repository: aggregates extraction and quality metrics (F291).

Extraction metrics come from PostgreSQL (documents.graph_extraction_status).
Entity and relation metrics come from Neo4j (gracefully degrade when unavailable).
Query metrics come from PostgreSQL usage-event telemetry emitted during GraphRAG queries.

All queries are org-scoped.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.graph.repositories._base import _get_driver_and_settings
from app.domains.graph.schemas.observability import (
    GraphEntityMetrics,
    GraphEntityTypeCount,
    GraphExtractionMetrics,
    GraphQueryMetrics,
    GraphRelationMetrics,
    GraphTrendPoint,
)
from app.models.document import Document
from app.models.usage import UsageEvent

logger = get_logger("graph.repositories.metrics")

# UsageEvent metadata keys written by the GraphRAG chat pipeline.
_GRAPH_CONTEXT_ENABLED_KEY = "graph_context_enabled"
_GRAPH_CONTEXT_USED_KEY = "graph_context_used"
_GRAPH_CONTEXT_UNAVAILABLE_KEY = "graph_context_unavailable"
_GRAPH_CONTEXT_REASON_KEY = "graph_context_reason"
_GRAPHRAG_EXPANSION_KEY = "graphrag_expansion_size"
_GRAPH_LATENCY_KEYS = ("answer_latency_ms", "latency_ms")
_GRAPHRAG_ACTION = "chat.completion"

# Confidence threshold below which an entity/relation is "low confidence".
_LOW_CONFIDENCE_THRESHOLD = 0.5


async def get_extraction_metrics(
    db: AsyncSession,
    *,
    organization_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
) -> GraphExtractionMetrics:
    """Aggregate graph extraction run stats from PostgreSQL document records."""
    stmt = select(Document.graph_extraction_status).where(
        Document.organization_id == organization_id,
        Document.updated_at >= from_dt,
        Document.updated_at <= to_dt,
    )
    rows = list((await db.execute(stmt)).scalars().all())

    counts: dict[str, int] = {}
    for status in rows:
        counts[status] = counts.get(status, 0) + 1

    succeeded = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    running = counts.get("extracting", 0)
    skipped = counts.get("skipped", 0)
    total = succeeded + failed + running + skipped + counts.get("pending", 0)
    finished = succeeded + failed
    success_rate = (succeeded / finished) if finished > 0 else None

    return GraphExtractionMetrics(
        total_runs=total,
        succeeded=succeeded,
        failed=failed,
        running=running,
        skipped=skipped,
        success_rate=success_rate,
        telemetry_missing=total == 0,
    )


async def get_entity_metrics(
    *,
    organization_id: UUID,
) -> GraphEntityMetrics:
    """Query Neo4j for entity counts and confidence distribution.

    Returns zero metrics with telemetry_missing=True when Neo4j is unavailable.
    """
    driver, settings = _get_driver_and_settings()
    if driver is None:
        return GraphEntityMetrics(
            total_entities=0,
            by_type=[],
            avg_confidence=None,
            low_confidence_count=0,
            telemetry_missing=True,
        )

    try:
        async with driver.session(database=settings.neo4j_database) as session:
            result = await asyncio.wait_for(
                session.run(
                    """
                    MATCH (e:Entity {organization_id: $organization_id})
                    RETURN
                        e.entity_type           AS entity_type,
                        count(*)                AS cnt,
                        avg(coalesce(e.confidence, 1.0)) AS avg_conf,
                        sum(CASE WHEN coalesce(e.confidence, 1.0) < $threshold THEN 1 ELSE 0 END)
                                                AS low_conf_cnt
                    ORDER BY cnt DESC
                    """,
                    organization_id=str(organization_id),
                    threshold=_LOW_CONFIDENCE_THRESHOLD,
                ),
                timeout=settings.neo4j_query_timeout_seconds,
            )
            records = await result.data()

        total = sum(int(r["cnt"]) for r in records)
        by_type = [
            GraphEntityTypeCount(
                entity_type=r["entity_type"] or "unknown",
                count=int(r["cnt"]),
                avg_confidence=float(r["avg_conf"]) if r["avg_conf"] is not None else None,
            )
            for r in records
        ]
        low_confidence_count = sum(int(r["low_conf_cnt"]) for r in records)
        avg_confidence = (
            sum(float(r["avg_conf"]) * int(r["cnt"]) for r in records if r["avg_conf"] is not None)
            / total
            if total > 0
            else None
        )
        return GraphEntityMetrics(
            total_entities=total,
            by_type=by_type,
            avg_confidence=avg_confidence,
            low_confidence_count=low_confidence_count,
            telemetry_missing=total == 0,
        )
    except Exception as exc:
        logger.warning(
            "graph.metrics.entity_error",
            organization_id=str(organization_id),
            error=exc.__class__.__name__,
            detail=str(exc),
        )
        return GraphEntityMetrics(
            total_entities=0,
            by_type=[],
            avg_confidence=None,
            low_confidence_count=0,
            telemetry_missing=True,
        )


async def get_relation_metrics(
    *,
    organization_id: UUID,
) -> GraphRelationMetrics:
    """Query Neo4j for relation counts and confidence distribution.

    Returns zero metrics with telemetry_missing=True when Neo4j is unavailable.
    """
    driver, settings = _get_driver_and_settings()
    if driver is None:
        return GraphRelationMetrics(
            total_relations=0,
            avg_confidence=None,
            low_confidence_count=0,
            telemetry_missing=True,
        )

    try:
        async with driver.session(database=settings.neo4j_database) as session:
            result = await asyncio.wait_for(
                session.run(
                    """
                    MATCH (r:Relation {organization_id: $organization_id})
                    RETURN
                        count(*)                AS total,
                        avg(coalesce(r.confidence, 1.0)) AS avg_conf,
                        sum(CASE WHEN coalesce(r.confidence, 1.0) < $threshold THEN 1 ELSE 0 END)
                                                AS low_conf_cnt
                    """,
                    organization_id=str(organization_id),
                    threshold=_LOW_CONFIDENCE_THRESHOLD,
                ),
                timeout=settings.neo4j_query_timeout_seconds,
            )
            records = await result.data()

        if not records:
            return GraphRelationMetrics(
                total_relations=0,
                avg_confidence=None,
                low_confidence_count=0,
                telemetry_missing=True,
            )
        row = records[0]
        total = int(row["total"])
        return GraphRelationMetrics(
            total_relations=total,
            avg_confidence=float(row["avg_conf"]) if row["avg_conf"] is not None else None,
            low_confidence_count=int(row["low_conf_cnt"]),
            telemetry_missing=total == 0,
        )
    except Exception as exc:
        logger.warning(
            "graph.metrics.relation_error",
            organization_id=str(organization_id),
            error=exc.__class__.__name__,
            detail=str(exc),
        )
        return GraphRelationMetrics(
            total_relations=0,
            avg_confidence=None,
            low_confidence_count=0,
            telemetry_missing=True,
        )


async def get_query_metrics(
    db: AsyncSession,
    *,
    organization_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
) -> GraphQueryMetrics:
    """Aggregate GraphRAG query metrics from usage-event metadata.

    The chat pipeline writes graph context telemetry into UsageEvent.metadata_json
    when GraphRAG is invoked. Returns telemetry_missing=True when no graph-enabled
    chat completion events exist in the selected range.
    """
    stmt = select(UsageEvent).where(
        UsageEvent.organization_id == organization_id,
        UsageEvent.created_at >= from_dt,
        UsageEvent.created_at <= to_dt,
        UsageEvent.event_type == _GRAPHRAG_ACTION,
    )
    rows = list((await db.execute(stmt)).scalars().all())

    graphrag_rows = [
        r
        for r in rows
        if isinstance(r.metadata_json, dict)
        and r.metadata_json.get(_GRAPH_CONTEXT_ENABLED_KEY) is True
    ]

    if not graphrag_rows:
        return GraphQueryMetrics(
            graphrag_queries=0,
            graphrag_failures=0,
            failure_rate=None,
            avg_expansion_size=None,
            avg_latency_ms=None,
            p95_latency_ms=None,
            fallback_to_rag=0,
            fallback_rate=None,
            cypher_failures=0,
            cypher_failure_rate=None,
            telemetry_missing=True,
        )

    total = len(graphrag_rows)
    failures = sum(
        1 for r in graphrag_rows if r.metadata_json.get(_GRAPH_CONTEXT_UNAVAILABLE_KEY) is True
    )
    fallbacks = sum(
        1 for r in graphrag_rows if r.metadata_json.get(_GRAPH_CONTEXT_USED_KEY) is False
    )
    cypher_failures = sum(
        1
        for r in graphrag_rows
        if r.metadata_json.get(_GRAPH_CONTEXT_UNAVAILABLE_KEY) is True
        or (
            isinstance(r.metadata_json.get(_GRAPH_CONTEXT_REASON_KEY), str)
            and str(r.metadata_json.get(_GRAPH_CONTEXT_REASON_KEY))
            in {"neo4j_unavailable", "cypher_error", "cypher_failure"}
        )
    )
    expansion_sizes = [
        float(r.metadata_json[_GRAPHRAG_EXPANSION_KEY])
        for r in graphrag_rows
        if isinstance(r.metadata_json.get(_GRAPHRAG_EXPANSION_KEY), (int, float))
    ]
    latency_values: list[float] = []
    for row in graphrag_rows:
        for key in _GRAPH_LATENCY_KEYS:
            latency = row.metadata_json.get(key)
            if isinstance(latency, (int, float)):
                latency_values.append(float(latency))
                break
    avg_expansion = sum(expansion_sizes) / len(expansion_sizes) if expansion_sizes else None
    avg_latency = sum(latency_values) / len(latency_values) if latency_values else None
    p95_latency = _percentile(latency_values, 0.95)
    failure_rate = failures / total if total > 0 else None
    fallback_rate = fallbacks / total if total > 0 else None
    cypher_failure_rate = cypher_failures / total if total > 0 else None

    return GraphQueryMetrics(
        graphrag_queries=total,
        graphrag_failures=failures,
        failure_rate=failure_rate,
        avg_expansion_size=avg_expansion,
        avg_latency_ms=avg_latency,
        p95_latency_ms=p95_latency,
        fallback_to_rag=fallbacks,
        fallback_rate=fallback_rate,
        cypher_failures=cypher_failures,
        cypher_failure_rate=cypher_failure_rate,
        telemetry_missing=False,
    )


async def get_trend_metrics(
    db: AsyncSession,
    *,
    organization_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
) -> list[GraphTrendPoint]:
    """Compute daily trend points for extraction and GraphRAG quality."""
    extraction_stmt = select(Document.updated_at, Document.graph_extraction_status).where(
        Document.organization_id == organization_id,
        Document.updated_at >= from_dt,
        Document.updated_at <= to_dt,
    )
    query_stmt = select(UsageEvent.created_at, UsageEvent.metadata_json).where(
        UsageEvent.organization_id == organization_id,
        UsageEvent.created_at >= from_dt,
        UsageEvent.created_at <= to_dt,
        UsageEvent.event_type == _GRAPHRAG_ACTION,
    )

    extraction_rows = list((await db.execute(extraction_stmt)).all())
    query_rows = list((await db.execute(query_stmt)).all())

    extraction_buckets: dict[date, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "succeeded": 0, "failed": 0}
    )
    query_buckets: dict[date, dict[str, object]] = defaultdict(
        lambda: {"total": 0, "failures": 0, "fallbacks": 0, "cypher": 0, "latencies": []}
    )

    for updated_at, status in extraction_rows:
        if not isinstance(updated_at, datetime):
            continue
        bucket = extraction_buckets[updated_at.date()]
        bucket["total"] += 1
        if status == "completed":
            bucket["succeeded"] += 1
        elif status == "failed":
            bucket["failed"] += 1

    for created_at, metadata_json in query_rows:
        if not isinstance(created_at, datetime) or not isinstance(metadata_json, dict):
            continue
        if metadata_json.get(_GRAPH_CONTEXT_ENABLED_KEY) is not True:
            continue
        bucket = query_buckets[created_at.date()]
        bucket["total"] = int(bucket["total"]) + 1
        if metadata_json.get(_GRAPH_CONTEXT_UNAVAILABLE_KEY) is True:
            bucket["failures"] = int(bucket["failures"]) + 1
            bucket["cypher"] = int(bucket["cypher"]) + 1
        if metadata_json.get(_GRAPH_CONTEXT_USED_KEY) is False:
            bucket["fallbacks"] = int(bucket["fallbacks"]) + 1
        for key in _GRAPH_LATENCY_KEYS:
            latency = metadata_json.get(key)
            if isinstance(latency, (int, float)):
                latencies = bucket["latencies"]
                assert isinstance(latencies, list)
                latencies.append(float(latency))
                break

    points: list[GraphTrendPoint] = []
    current_day = from_dt.date()
    end_day = to_dt.date()
    while current_day <= end_day:
        extraction_bucket = extraction_buckets[current_day]
        query_bucket = query_buckets[current_day]
        latencies = query_bucket["latencies"]
        assert isinstance(latencies, list)
        query_total = int(query_bucket["total"])
        failures = int(query_bucket["failures"])
        fallbacks = int(query_bucket["fallbacks"])
        cypher_failures = int(query_bucket["cypher"])
        total_extraction = int(extraction_bucket["total"])
        failed = int(extraction_bucket["failed"])
        extraction_failure_rate = failed / total_extraction if total_extraction > 0 else None
        query_failure_rate = failures / query_total if query_total > 0 else None
        fallback_rate = fallbacks / query_total if query_total > 0 else None
        avg_latency = sum(latencies) / len(latencies) if latencies else None

        points.append(
            GraphTrendPoint(
                day=current_day,
                extraction_runs=total_extraction,
                extraction_failure_rate=extraction_failure_rate,
                graphrag_queries=query_total,
                graphrag_failure_rate=query_failure_rate,
                fallback_rate=fallback_rate,
                avg_latency_ms=avg_latency,
                cypher_failures=cypher_failures,
            )
        )
        current_day = date.fromordinal(current_day.toordinal() + 1)

    return points


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * pct
    lower = int(idx)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = idx - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac
