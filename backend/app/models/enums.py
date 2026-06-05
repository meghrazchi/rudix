from enum import StrEnum


class OrganizationRole(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class DocumentFileType(StrEnum):
    pdf = "pdf"
    txt = "txt"
    docx = "docx"


class DocumentStatus(StrEnum):
    uploaded = "uploaded"
    processing = "processing"
    indexed = "indexed"
    failed = "failed"
    quarantined = "quarantined"
    blocked = "blocked"
    delete_requested = "delete_requested"
    deleting = "deleting"
    deleted = "deleted"
    retained_by_policy = "retained_by_policy"


class ConnectorAuthType(StrEnum):
    none = "none"
    oauth2 = "oauth2"
    api_token = "api_token"
    service_account = "service_account"
    basic = "basic"


class ConnectorCapability(StrEnum):
    webhooks = "webhooks"
    attachments = "attachments"
    comments = "comments"
    folders = "folders"
    acls = "acls"
    delta_sync = "delta_sync"
    rate_limits = "rate_limits"
    export_formats = "export_formats"


class ConnectorConnectionStatus(StrEnum):
    active = "active"
    disabled = "disabled"
    error = "error"
    revoked = "revoked"


class ConnectorCredentialStatus(StrEnum):
    active = "active"
    expired = "expired"
    revoked = "revoked"
    error = "error"


class ConnectorSyncJobStatus(StrEnum):
    active = "active"
    paused = "paused"
    disabled = "disabled"


class ConnectorSyncRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ExternalItemType(StrEnum):
    issue = "issue"
    wiki_page = "wiki_page"
    cloud_file = "cloud_file"
    folder = "folder"
    comment = "comment"
    attachment = "attachment"


class ExternalItemVisibility(StrEnum):
    org_wide = "org_wide"
    collection = "collection"
    restricted = "restricted"


class DocumentProfile(StrEnum):
    text_based = "text_based"
    scanned = "scanned"
    mixed = "mixed"
    table_heavy = "table_heavy"
    figure_heavy = "figure_heavy"
    form_like = "form_like"
    encrypted = "encrypted"
    corrupted = "corrupted"
    unsupported = "unsupported"


class ChatRole(StrEnum):
    user = "user"
    assistant = "assistant"
    system = "system"


class EvaluationRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class AgentRunStatus(StrEnum):
    queued = "queued"
    planning = "planning"
    running = "running"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AgentStepStatus(StrEnum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class AgentToolCallStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class AgentApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    cancelled = "cancelled"


class FeedbackRating(StrEnum):
    up = "up"
    down = "down"


class FeedbackReason(StrEnum):
    wrong_citation = "wrong_citation"
    hallucination = "hallucination"
    outdated_source = "outdated_source"
    missing_document = "missing_document"
    unsafe_content = "unsafe_content"
    other = "other"


class NotificationEventType(StrEnum):
    upload_indexed = "upload_indexed"
    upload_failed = "upload_failed"
    evaluation_complete = "evaluation_complete"
    evaluation_failed = "evaluation_failed"
    invite_received = "invite_received"
    security_warning = "security_warning"
    quota_warning = "quota_warning"
    connector_sync_issue = "connector_sync_issue"


class NotificationSeverity(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class FeedbackReviewStatus(StrEnum):
    new = "new"
    triaged = "triaged"
    needs_document = "needs_document"
    eval_created = "eval_created"
    fixed = "fixed"
    rejected = "rejected"
    duplicate = "duplicate"


class FeedbackSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class SafetyViolationType(StrEnum):
    injection = "injection"
    cross_tenant_leakage = "cross_tenant_leakage"
    private_source_exposure = "private_source_exposure"
    unsupported_claims = "unsupported_claims"
    malicious_document = "malicious_document"
    unsafe_transform = "unsafe_transform"


class SafetyEvalSeverity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class EvaluationDatasetStatus(StrEnum):
    draft = "draft"
    published = "published"


class EvaluationCaseDifficulty(StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class QualityGateVerdict(StrEnum):
    passed = "passed"
    failed = "failed"
    overridden = "overridden"


class RagCitationStrictness(StrEnum):
    strict = "strict"
    moderate = "moderate"
    lenient = "lenient"


class RagSafetyMode(StrEnum):
    strict = "strict"
    standard = "standard"
    permissive = "permissive"


class PromptTemplateKey(StrEnum):
    answer_generation = "answer_generation"
    summarization = "summarization"
    comparison = "comparison"
    citation_validation = "citation_validation"
    agent_planning = "agent_planning"


class PromptTemplateVersionState(StrEnum):
    draft = "draft"
    review = "review"
    published = "published"
