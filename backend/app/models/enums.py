from enum import StrEnum


class OrganizationRole(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"
    reviewer = "reviewer"
    security_admin = "security_admin"
    billing_admin = "billing_admin"
    developer = "developer"


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
    # Connector file ingestion statuses (F245)
    pending_scan = "pending_scan"
    infected = "infected"
    extraction_failed = "extraction_failed"
    ocr_applied = "ocr_applied"
    skipped = "skipped"
    unsupported = "unsupported"


class GraphExtractionStatus(StrEnum):
    pending = "pending"
    extracting = "extracting"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class DocumentIngestionSource(StrEnum):
    upload = "upload"
    connector = "connector"


class DocumentTrustStatus(StrEnum):
    draft = "draft"
    current = "current"
    verified = "verified"
    stale = "stale"
    deprecated = "deprecated"
    superseded = "superseded"
    expired = "expired"


class DocumentQualityState(StrEnum):
    draft = "draft"
    verified = "verified"
    reviewed = "reviewed"
    unreviewed = "unreviewed"
    stale = "stale"
    expired = "expired"
    deprecated = "deprecated"
    archived = "archived"


class DocumentReviewStatus(StrEnum):
    current = "current"
    trusted = "trusted"
    needs_review = "needs_review"
    stale = "stale"
    expired = "expired"
    archived = "archived"


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
    files = "files"
    acls = "acls"
    delta_sync = "delta_sync"
    deletions = "deletions"
    rate_limits = "rate_limits"
    export_formats = "export_formats"
    deep_links = "deep_links"


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


class SyncConflictType(StrEnum):
    acl_changed = "acl_changed"
    renamed = "renamed"
    moved = "moved"
    permission_revoked = "permission_revoked"


class SyncConflictStatus(StrEnum):
    open = "open"
    resolved = "resolved"
    dismissed = "dismissed"


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
    changes_requested = "changes_requested"
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


class FeedbackCategory(StrEnum):
    wrong_answer = "wrong_answer"
    bad_citation = "bad_citation"
    outdated_source = "outdated_source"
    missing_information = "missing_information"
    low_confidence = "low_confidence"
    unsafe_response = "unsafe_response"
    # F316 — trust-panel-specific accuracy categories
    missing_citation = "missing_citation"
    stale_source = "stale_source"
    conflicting_source = "conflicting_source"
    not_enough_detail = "not_enough_detail"
    should_have_said_not_found = "should_have_said_not_found"


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
    # F316 — reviewer has accepted the item for investigation (between triaged and fixed)
    accepted = "accepted"
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


class EmailProviderType(StrEnum):
    console = "console"
    smtp = "smtp"
    resend = "resend"
    postmark = "postmark"


class EmailEventType(StrEnum):
    invite_received = "invite_received"
    upload_failed = "upload_failed"
    upload_indexed = "upload_indexed"
    connector_sync_failed = "connector_sync_failed"
    billing_warning = "billing_warning"
    quota_warning = "quota_warning"
    security_alert = "security_alert"


class EmailDeliveryStatus(StrEnum):
    queued = "queued"
    sent = "sent"
    failed = "failed"
    bounced = "bounced"
    unsubscribed = "unsubscribed"


class OcrQualityStatus(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    failed = "failed"
    not_required = "not_required"


class AbExperimentStatus(StrEnum):
    draft = "draft"
    running = "running"
    completed = "completed"
    failed = "failed"


class AbVariantApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class DocumentVersionChangeReason(StrEnum):
    initial_upload = "initial_upload"
    content_update = "content_update"
    metadata_update = "metadata_update"
    connector_sync = "connector_sync"
    reindex = "reindex"
    tombstone = "tombstone"


class VerifiedAnswerStatus(StrEnum):
    draft = "draft"
    pending_review = "pending_review"
    approved = "approved"
    published = "published"
    archived = "archived"
