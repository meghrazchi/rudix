from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

UsageGranularity = Literal["day", "week", "month"]
AuditResultFilter = Literal["all", "success", "failure", "unknown"]
AuditEventResult = Literal["success", "failure", "unknown"]
AuditExportFormat = Literal["csv", "json"]
UsageExportFormat = Literal["csv", "json"]
FeatureArea = Literal["chat", "agent", "evaluation", "pipeline", "api", "all"]


class UsageSummaryRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")


class UsageSummaryTotalsResponse(BaseModel):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    event_count: int
    avg_confidence: float | None = None
    avg_latency_ms: float | None = None
    latency_score: float | None = None


class UsageSummaryPointResponse(BaseModel):
    period_start: date
    period_end: date
    input_tokens: int
    output_tokens: int
    cost_usd: float
    event_count: int
    avg_confidence: float | None = None
    avg_latency_ms: float | None = None
    latency_score: float | None = None


class UsageSummaryResponse(BaseModel):
    organization_id: str
    range: UsageSummaryRange
    granularity: UsageGranularity
    totals: UsageSummaryTotalsResponse
    series: list[UsageSummaryPointResponse]


class AuditLogListItemResponse(BaseModel):
    audit_log_id: str
    organization_id: str
    user_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    request_id: str | None = None
    result: AuditEventResult
    severity: str | None = None
    ip_address: str | None = None
    session_id: str | None = None
    document_id: str | None = None
    collection_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogListItemResponse]
    total: int
    limit: int
    offset: int
    range: UsageSummaryRange


class AgentDiagnosticsTotalsResponse(BaseModel):
    runs_started: int
    runs_completed: int
    runs_failed: int
    runs_waiting_approval: int
    runs_cancelled: int
    steps_executed: int
    tool_calls_executed: int
    tool_calls_succeeded: int
    tool_calls_failed: int
    approvals_requested: int
    approvals_approved: int
    approvals_rejected: int
    total_tokens: int
    total_cost_usd: float
    avg_confidence: float | None = None


class AgentDiagnosticsPointResponse(BaseModel):
    period_start: date
    period_end: date
    runs_started: int
    runs_completed: int
    runs_failed: int
    runs_waiting_approval: int
    runs_cancelled: int
    steps_executed: int
    tool_calls_executed: int
    tool_calls_succeeded: int
    tool_calls_failed: int
    approvals_requested: int
    approvals_approved: int
    approvals_rejected: int
    total_tokens: int
    total_cost_usd: float
    avg_confidence: float | None = None


class AgentDiagnosticsResponse(BaseModel):
    organization_id: str
    range: UsageSummaryRange
    totals: AgentDiagnosticsTotalsResponse
    series: list[AgentDiagnosticsPointResponse]
    errors_by_code: dict[str, int] = Field(default_factory=dict)
    audit_actions: dict[str, int] = Field(default_factory=dict)


# ── Usage Dashboard (F153) ────────────────────────────────────────────────────


class TopUserUsageResponse(BaseModel):
    user_id: str
    questions: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class TopModelUsageResponse(BaseModel):
    model_name: str
    event_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class UsageDashboardTotalsResponse(BaseModel):
    questions_asked: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    active_users: int
    documents: int
    indexed_documents: int
    total_chunks: int
    indexing_jobs: int
    failed_indexing_jobs: int
    evaluation_runs: int
    agent_runs: int
    api_calls: int
    avg_confidence: float | None = None
    avg_latency_ms: float | None = None
    latency_score: float | None = None


class UsageDashboardPointResponse(BaseModel):
    period_start: date
    period_end: date
    questions_asked: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    active_users: int
    agent_runs: int
    evaluation_runs: int
    avg_confidence: float | None = None
    avg_latency_ms: float | None = None


class UsageDashboardResponse(BaseModel):
    organization_id: str
    range: UsageSummaryRange
    granularity: UsageGranularity
    is_cost_estimate: bool
    totals: UsageDashboardTotalsResponse
    series: list[UsageDashboardPointResponse]
    top_users: list[TopUserUsageResponse]
    top_models: list[TopModelUsageResponse]
    feature_area_breakdown: dict[str, int] = Field(default_factory=dict)
