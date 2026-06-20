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

_REMEDIATION: dict[str, list[str]] = {
    "role_allow_resource_deny": [
        "Review the explicit deny entry and remove it if access should be granted.",
        "If the deny is intentional, revoke the conflicting grant.",
        "Consider whether this principal requires a narrower role instead of a broad grant.",
    ],
    "collection_allow_connector_acl_deny": [
        "Re-sync the connector ACL to ensure collection-level access is reflected.",
        "Remove the collection grant if the connector ACL restriction is correct.",
        "Contact the connector administrator to update ACL permissions upstream.",
    ],
    "stale_grant_deleted_resource": [
        "Revoke the grant as the target resource no longer exists.",
        "Audit other grants from the same principal for additional stale entries.",
    ],
    "stale_grant_removed_connector": [
        "Revoke the connector grant and re-create it if the connector is re-connected.",
        "Verify the connector is still active before granting connector-scoped access.",
    ],
    "orphaned_acl_mapping": [
        "Remove ACL mappings for connectors that have been deleted or disconnected.",
        "Re-run the connector sync to generate fresh ACL mappings.",
    ],
    "feature_deny_active_grant": [
        "If the feature is intentionally disabled, revoke conflicting explicit grants.",
        "Enable the feature for this organisation if grant-level access is correct.",
    ],
    "explicit_grant_conflicts_role_deny": [
        "Review whether the explicit grant is intentional given the role restriction.",
        "Downgrade the principal's role if the grant should be the limiting factor.",
    ],
    "citation_visible_source_hidden": [
        "Revoke citation-level access until the underlying source is also accessible.",
        "Grant the principal access to the source document backing the citation.",
    ],
    "graph_entity_visible_evidence_inaccessible": [
        "Ensure the principal has access to evidence documents backing the entity.",
        "If evidence documents are restricted, restrict graph entity access to match.",
    ],
}


def remediation_for(conflict_type: str) -> list[str]:
    return _REMEDIATION.get(conflict_type, ["Review this conflict manually with an administrator."])


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
