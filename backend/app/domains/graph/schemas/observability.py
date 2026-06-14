"""Pydantic schemas for graph observability metrics (F291)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GraphAlertLevel = Literal["warning", "critical"]


class GraphAlertItem(BaseModel):
    level: GraphAlertLevel
    metric: str
    message: str


class GraphObservabilityRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")


class GraphExtractionMetrics(BaseModel):
    total_runs: int
    succeeded: int
    failed: int
    running: int
    skipped: int
    success_rate: float | None
    telemetry_missing: bool


class GraphEntityTypeCount(BaseModel):
    entity_type: str
    count: int
    avg_confidence: float | None


class GraphEntityMetrics(BaseModel):
    total_entities: int
    by_type: list[GraphEntityTypeCount]
    avg_confidence: float | None
    low_confidence_count: int
    telemetry_missing: bool


class GraphRelationMetrics(BaseModel):
    total_relations: int
    avg_confidence: float | None
    low_confidence_count: int
    telemetry_missing: bool


class GraphQueryMetrics(BaseModel):
    graphrag_queries: int
    graphrag_failures: int
    failure_rate: float | None
    avg_expansion_size: float | None
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    fallback_to_rag: int
    fallback_rate: float | None
    cypher_failures: int
    cypher_failure_rate: float | None
    telemetry_missing: bool


class GraphAlertThresholds(BaseModel):
    extraction_failure_rate_max: float = Field(default=0.2, ge=0.0, le=1.0)
    query_failure_rate_max: float = Field(default=0.1, ge=0.0, le=1.0)
    graphrag_fallback_rate_max: float = Field(default=0.3, ge=0.0, le=1.0)
    low_confidence_entity_rate_max: float = Field(default=0.3, ge=0.0, le=1.0)
    query_latency_ms_max: float = Field(default=2000.0, ge=0.0)


class GraphTrendPoint(BaseModel):
    day: date
    extraction_runs: int
    extraction_failure_rate: float | None
    graphrag_queries: int
    graphrag_failure_rate: float | None
    fallback_rate: float | None
    avg_latency_ms: float | None
    cypher_failures: int


class GraphObservabilitySnapshot(BaseModel):
    organization_id: str
    range: GraphObservabilityRange
    generated_at: datetime
    graph_enabled: bool
    neo4j_reachable: bool
    extraction: GraphExtractionMetrics
    entities: GraphEntityMetrics
    relations: GraphRelationMetrics
    queries: GraphQueryMetrics
    thresholds: GraphAlertThresholds
    alerts: list[GraphAlertItem]
    trends: list[GraphTrendPoint]
