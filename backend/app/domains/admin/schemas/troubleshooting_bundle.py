"""Schemas for F329: Safe troubleshooting bundle export."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BundleSourceType(StrEnum):
    chat_message = "chat_message"
    document = "document"
    connector_sync = "connector_sync"
    evaluation_run = "evaluation_run"
    failed_job = "failed_job"


class BundleRedactionConfig(BaseModel):
    redact_prompts: bool = True
    redact_snippets: bool = True
    redact_pii: bool = True
    redact_source_content: bool = True
    # When False, log lines are omitted entirely rather than redacted
    include_redacted_logs: bool = True


class TroubleshootingBundleRequest(BaseModel):
    source_type: BundleSourceType
    source_id: UUID
    include_markdown: bool = False
    redaction: BundleRedactionConfig = Field(default_factory=BundleRedactionConfig)


# ── Sub-schemas for bundle sections ────────────────────────────────────────────


class BundleIdentifiers(BaseModel):
    bundle_id: str
    source_type: str
    source_id: str
    organization_id: str
    trace_id: str | None = None
    request_id: str | None = None
    celery_task_id: str | None = None


class BundleLifecycleStage(BaseModel):
    stage: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class BundleRetrievalDiagnostics(BaseModel):
    profile_key: str | None = None
    strategy: str | None = None
    top_k: int | None = None
    reranker_enabled: bool | None = None
    reranker_model: str | None = None
    hybrid_enabled: bool | None = None
    query_rewriting_enabled: bool | None = None
    result_count: int | None = None
    scores: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BundleCitation(BaseModel):
    citation_index: int
    document_id: str
    document_filename: str | None = None
    page_number: int | None = None
    trust_status: str | None = None
    freshness_status: str | None = None
    ocr_quality_status: str | None = None
    retrieval_score: float | None = None
    rerank_score: float | None = None


class BundleModelMetadata(BaseModel):
    model_name: str | None = None
    provider_type: str | None = None
    provider_profile: str | None = None
    model_profile_key: str | None = None
    token_input_count: int | None = None
    token_output_count: int | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None


class BundleLogEntry(BaseModel):
    timestamp: datetime | None = None
    level: str
    event: str
    redacted: bool = False
    fields: dict[str, Any] = Field(default_factory=dict)


class BundleConfigFingerprint(BaseModel):
    rag_profile_key: str | None = None
    chunking_profile_id: str | None = None
    answer_language_mode: str | None = None
    collection_ids: list[str] = Field(default_factory=list)
    feature_flags: list[str] = Field(default_factory=list)


class BundleWarning(BaseModel):
    code: str
    message: str
    severity: str = "warning"


# ── Source-specific detail schemas ──────────────────────────────────────────────


class ChatMessageBundleDetail(BaseModel):
    session_id: str | None = None
    role: str | None = None
    confidence_score: float | None = None
    answer_truncated: bool = False
    scope_mode: str | None = None
    grounded_verification_passed: bool | None = None
    policy_enforced: bool | None = None
    policy_action: str | None = None
    retrieval: BundleRetrievalDiagnostics | None = None
    citations: list[BundleCitation] = Field(default_factory=list)
    model: BundleModelMetadata | None = None


class DocumentBundleDetail(BaseModel):
    filename: str | None = None
    file_type: str | None = None
    status: str | None = None
    trust_status: str | None = None
    quality_state: str | None = None
    language: str | None = None
    language_confidence: float | None = None
    ocr_quality_status: str | None = None
    page_count: int | None = None
    chunk_count: int | None = None
    word_count: int | None = None
    extraction_strategy: str | None = None
    pipeline_stages: list[BundleLifecycleStage] = Field(default_factory=list)


class ConnectorSyncBundleDetail(BaseModel):
    sync_job_id: str | None = None
    connection_id: str | None = None
    trigger_type: str | None = None
    status: str | None = None
    sync_version: int | None = None
    items_seen: int | None = None
    items_upserted: int | None = None
    items_deleted: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message_redacted: bool = False
    error_code: str | None = None
    conflict_count: int | None = None


class EvaluationRunBundleDetail(BaseModel):
    evaluation_set_id: str | None = None
    status: str | None = None
    model_profile_key: str | None = None
    provider_type: str | None = None
    provider_profile: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total_questions: int | None = None
    avg_retrieval_score: float | None = None
    avg_faithfulness_score: float | None = None
    avg_latency_ms: float | None = None
    failed_count: int | None = None


class FailedJobBundleDetail(BaseModel):
    task_name: str | None = None
    job_type: str | None = None
    queue_name: str | None = None
    status: str | None = None
    error_code: str | None = None
    attempt_count: int | None = None
    is_retryable: bool | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    last_attempted_at: datetime | None = None


# ── Top-level bundle response ───────────────────────────────────────────────────


class TroubleshootingBundleResponse(BaseModel):
    schema_version: str = "1.0"
    bundle_id: str
    generated_at: datetime
    exported_by_user_id: str
    organization_id: str
    source_type: str
    source_id: str
    redaction_config: BundleRedactionConfig
    identifiers: BundleIdentifiers
    lifecycle_stages: list[BundleLifecycleStage] = Field(default_factory=list)
    config_fingerprint: BundleConfigFingerprint | None = None
    warnings: list[BundleWarning] = Field(default_factory=list)
    detail: (
        ChatMessageBundleDetail
        | DocumentBundleDetail
        | ConnectorSyncBundleDetail
        | EvaluationRunBundleDetail
        | FailedJobBundleDetail
        | None
    ) = None
    logs: list[BundleLogEntry] = Field(default_factory=list)
    markdown_summary: str | None = None
