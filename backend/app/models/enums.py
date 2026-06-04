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
