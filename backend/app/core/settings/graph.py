"""Enterprise graph (Neo4j) and GraphRAG settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    field_validator,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class GraphSettings(BaseModel):
    feature_enable_graph_rag: bool = False
    # graph_extraction gates the entity/relation extraction pipeline per org.
    # graph_explorer gates the read-only graph explorer UI per org.
    feature_enable_graph_extraction: bool = False
    feature_enable_graph_explorer: bool = True
    # Enterprise Graph (Neo4j) — F279
    # Set ENTERPRISE_GRAPH_ENABLED=true and configure the bolt URI + credentials to activate.
    # When disabled, all upload/chat/RAG flows operate normally without Neo4j.
    # WARNING: neo4j_password is sensitive — never log or return it in API responses.
    enterprise_graph_enabled: bool = False
    neo4j_uri: str | None = Field(default=None, max_length=255)
    # None = run graph migrations at API startup in development/test only.
    graph_migrations_on_startup: bool | None = None
    neo4j_username: str | None = Field(default=None, max_length=128)
    neo4j_password: SecretStr | None = None
    neo4j_database: str = Field(default="neo4j", min_length=1, max_length=128)
    neo4j_connection_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    neo4j_query_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    neo4j_max_connection_pool_size: int = Field(default=50, ge=1, le=500)
    # Entity extraction pipeline (F283): LLM-based entity extraction from document chunks.
    # Requires enterprise_graph_enabled=true. Set FEATURE_ENABLE_ENTITY_EXTRACTION=true to activate.
    # strict_mode=true aborts the document pipeline on extraction failure (default: continue).
    feature_enable_entity_extraction: bool = False
    entity_extraction_batch_size: int = Field(default=10, ge=1, le=50)
    entity_extraction_strict_mode: bool = False
    entity_extraction_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    entity_extraction_max_retries: int = Field(default=2, ge=0, le=5)
    # Entity resolution and canonicalization (F285): merges aliases and source
    # mentions into canonical records when the confidence threshold is met.
    # Requires enterprise_graph_enabled=true. Remains off by default.
    feature_enable_entity_resolution: bool = False
    entity_resolution_auto_merge_threshold: float = Field(default=0.88, ge=0.0, le=1.0)
    entity_resolution_review_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    # Relation extraction pipeline (F284): LLM-based relation extraction, runs after entity
    # extraction. Requires enterprise_graph_enabled=true and feature_enable_entity_extraction=true.
    # confidence_threshold: relations below this value receive status=low_confidence.
    # review_mode: when true, all relations start as unverified regardless of confidence.
    # strict_mode: when true, pipeline fails on extraction error (default: continue).
    feature_enable_relation_extraction: bool = False
    relation_extraction_batch_size: int = Field(default=10, ge=1, le=50)
    relation_extraction_strict_mode: bool = False
    relation_extraction_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    relation_extraction_max_retries: int = Field(default=2, ge=0, le=5)
    relation_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    relation_extraction_review_mode: bool = False
    graph_rag_max_hops: int = Field(default=2, ge=1, le=5)
    graph_rag_max_related_entities: int = Field(default=8, ge=1, le=50)
    graph_rag_max_chunks: int = Field(default=5, ge=1, le=50)
    graph_rag_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    graph_rag_relation_type_allowlist: list[str] = Field(
        default_factory=lambda: [
            "RELATES_TO",
            "OWNS",
            "COVERS_CONTROL",
            "CONTAINS_OBLIGATION",
            "PROVIDES_SERVICE_TO",
            "SUPERSEDES",
            "AFFECTS",
            "DEPENDS_ON",
        ]
    )
    # Graph observability alert thresholds (F291).
    # Admins can override these via environment variables to tune alerting sensitivity.
    # extraction_failure_rate_max: fraction of extraction runs that must fail to trigger an alert.
    # query_failure_rate_max: fraction of GraphRAG queries that must fail to trigger an alert.
    # graphrag_fallback_rate_max: fraction of GraphRAG queries that fall back to standard RAG.
    # low_confidence_entity_rate_max: fraction of entities with confidence < 0.5.
    # query_latency_ms_max: p95 GraphRAG latency ceiling in milliseconds.
    graph_alert_extraction_failure_rate_max: float = Field(default=0.2, ge=0.0, le=1.0)
    graph_alert_query_failure_rate_max: float = Field(default=0.1, ge=0.0, le=1.0)
    graph_alert_graphrag_fallback_rate_max: float = Field(default=0.3, ge=0.0, le=1.0)
    graph_alert_low_confidence_entity_rate_max: float = Field(default=0.3, ge=0.0, le=1.0)
    graph_alert_query_latency_ms_max: float = Field(default=2000.0, ge=0.0)

    @field_validator("graph_rag_relation_type_allowlist", mode="before")
    @classmethod
    def validate_graph_rag_relation_types(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError(
                "graph_rag_relation_type_allowlist must be a comma-separated string or list"
            )

        normalized: list[str] = []
        for relation_type in raw_items:
            if not relation_type:
                continue
            upper = relation_type.upper()
            if upper not in normalized:
                normalized.append(upper)
        if not normalized:
            raise ValueError("graph_rag_relation_type_allowlist must contain at least one value")
        return normalized

    @field_validator("neo4j_uri")
    @classmethod
    def validate_neo4j_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        allowed = ("bolt://", "neo4j://", "bolt+s://", "neo4j+s://", "bolt+ssc://", "neo4j+ssc://")
        if not any(cleaned.lower().startswith(scheme) for scheme in allowed):
            raise ValueError(
                "neo4j_uri must start with bolt://, neo4j://, bolt+s://, or neo4j+s://"
            )
        return cleaned


def validate_enterprise_graph(settings: Settings) -> None:
    if settings.enterprise_graph_enabled:
        if not settings.neo4j_uri:
            raise ValueError("neo4j_uri is required when enterprise_graph_enabled=true")
        if not settings.neo4j_username:
            raise ValueError("neo4j_username is required when enterprise_graph_enabled=true")
        if (
            settings.neo4j_password is None
            or not settings._secret_value(settings.neo4j_password).strip()
        ):
            raise ValueError("neo4j_password is required when enterprise_graph_enabled=true")


def validate_graph_rag(settings: Settings) -> None:
    settings.graph_rag_relation_type_allowlist = [
        relation_type.strip().upper()
        for relation_type in settings.graph_rag_relation_type_allowlist
        if relation_type.strip()
    ]
    if not settings.graph_rag_relation_type_allowlist:
        raise ValueError("graph_rag_relation_type_allowlist must contain at least one value")
