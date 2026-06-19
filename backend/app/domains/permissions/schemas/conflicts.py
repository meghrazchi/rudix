from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Conflict severity / status constants ──────────────────────────────────────

# DB uses: low / medium / high / critical
# API surface uses: info / warning / blocking / security_risk (maps below)
SEVERITY_TO_DB: dict[str, str] = {
    "info": "low",
    "warning": "medium",
    "blocking": "high",
    "security_risk": "critical",
}
DB_TO_SEVERITY: dict[str, str] = {v: k for k, v in SEVERITY_TO_DB.items()}

CONFLICT_TYPES = (
    "role_allow_resource_deny",
    "collection_allow_connector_acl_deny",
    "citation_visible_source_hidden",
    "graph_entity_visible_evidence_inaccessible",
    "stale_grant_deleted_resource",
    "stale_grant_removed_connector",
    "orphaned_acl_mapping",
    "feature_deny_active_grant",
    "explicit_grant_conflicts_role_deny",
)

CONFLICT_STATUSES = ("open", "investigating", "resolved", "dismissed")

SEVERITY_LABELS = ("info", "warning", "blocking", "security_risk")


# ── Response models ────────────────────────────────────────────────────────────

class ConflictResponse(BaseModel):
    id: str
    organization_id: str
    subject_type: str
    subject_value: str
    user_id: str | None
    role_name: str | None
    resource_type: str
    resource_id: str | None
    action: str
    conflict_type: str
    severity: str  # API surface: info/warning/blocking/security_risk
    status: str
    detected_at: datetime
    resolved_at: datetime | None
    conflict_summary: str | None
    grant_id: str | None
    deny_id: str | None
    remediation: list[str]
    context: dict


class ConflictListResponse(BaseModel):
    items: list[ConflictResponse]
    total: int
    page: int
    page_size: int


class UpdateConflictStatusRequest(BaseModel):
    status: Literal["investigating", "resolved", "dismissed"]
    resolution_note: str | None = Field(default=None, max_length=1024)


class ScanResult(BaseModel):
    conflicts_detected: int
    conflicts_created: int
    scan_duration_ms: int
    scanned_grants: int
    scanned_denies: int
    scanned_acl_mappings: int


# ── Explain-decision models ───────────────────────────────────────────────────

class ExplainDecisionRequest(BaseModel):
    subject_user_id: str
    resource_type: str
    resource_id: str | None = None
    action: str


class TraceStep(BaseModel):
    rule: str
    outcome: str  # "pass", "allow", "deny"
    detail: str | None = None


class ExplainDecisionResponse(BaseModel):
    decision: str  # "allow" or "deny"
    matched_rule: str
    deny_reason: str | None
    subject_user_id: str
    resource_type: str
    resource_id: str | None
    action: str
    trace: list[TraceStep]
    remediation: list[str]
    request_id: str
