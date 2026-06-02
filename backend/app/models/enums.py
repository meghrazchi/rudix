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
    deleting = "deleting"
    deleted = "deleted"


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
