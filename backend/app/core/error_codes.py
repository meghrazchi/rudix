"""Stable machine-readable error codes for the API error envelope (R04-10).

``code_for`` resolves a code from, in order: a structured detail that already carries
``code``/``error``, the registry of the most frequent ``detail`` strings, and a status
fallback. Codes are part of the public contract; add new ones, never rename.
"""

from __future__ import annotations

from typing import Any

DETAIL_ERROR_CODES: dict[str, str] = {
    "AI response policy not found": "AI_RESPONSE_POLICY_NOT_FOUND",
    "API key not found": "API_KEY_NOT_FOUND",
    "Agent approval not found": "AGENT_APPROVAL_NOT_FOUND",
    "Agent run not found": "AGENT_RUN_NOT_FOUND",
    "Chat session not found": "CHAT_SESSION_NOT_FOUND",
    "Chunking profile not found": "CHUNKING_PROFILE_NOT_FOUND",
    "Collection not found": "COLLECTION_NOT_FOUND",
    "Conflict not found": "CONFLICT_NOT_FOUND",
    "Cursor pagination requires sort_by=created_at": "CURSOR_SORT_UNSUPPORTED",
    "Document not found": "DOCUMENT_NOT_FOUND",
    "Domain verification not found.": "DOMAIN_VERIFICATION_NOT_FOUND",
    "Evaluation question not found": "EVALUATION_QUESTION_NOT_FOUND",
    "Evaluation run not found": "EVALUATION_RUN_NOT_FOUND",
    "Evaluation set not found": "EVALUATION_SET_NOT_FOUND",
    "Experiment not found": "EXPERIMENT_NOT_FOUND",
    "Feedback not found": "FEEDBACK_NOT_FOUND",
    "Gate run not found": "GATE_RUN_NOT_FOUND",
    "Incident not found": "INCIDENT_NOT_FOUND",
    "Installation not found": "INSTALLATION_NOT_FOUND",
    "Invalid document_id format": "INVALID_DOCUMENT_ID_FORMAT",
    "Invalid organization context": "INVALID_ORGANIZATION_CONTEXT",
    "Invalid pagination cursor": "INVALID_CURSOR",
    "Invalid principal context": "INVALID_PRINCIPAL_CONTEXT",
    "Invalid user context": "INVALID_USER_CONTEXT",
    "Invitation not found": "INVITATION_NOT_FOUND",
    "Job not found": "JOB_NOT_FOUND",
    "Member not found": "MEMBER_NOT_FOUND",
    "Message not found": "MESSAGE_NOT_FOUND",
    "Metadata field not found": "METADATA_FIELD_NOT_FOUND",
    "No active organization context": "NO_ACTIVE_ORGANIZATION_CONTEXT",
    "No active organization context for principal": "NO_ACTIVE_ORGANIZATION_CONTEXT_FOR_PRINCIPAL",
    "Organization not found.": "ORGANIZATION_NOT_FOUND",
    "Pipeline run not found": "PIPELINE_RUN_NOT_FOUND",
    "Principal identity context is invalid": "PRINCIPAL_IDENTITY_CONTEXT_IS_INVALID",
    "Principal organization context is invalid": "PRINCIPAL_ORGANIZATION_CONTEXT_IS_INVALID",
    "Principal user context is invalid": "PRINCIPAL_USER_CONTEXT_IS_INVALID",
    "Quality gate not found": "QUALITY_GATE_NOT_FOUND",
    "RAG profile not found": "RAG_PROFILE_NOT_FOUND",
    "Review item not found": "REVIEW_ITEM_NOT_FOUND",
    "Role not found": "ROLE_NOT_FOUND",
    "Safety eval run not found": "SAFETY_EVAL_RUN_NOT_FOUND",
    "Service account not found": "SERVICE_ACCOUNT_NOT_FOUND",
    "Share link not found, expired, or revoked.": "SHARE_LINK_NOT_FOUND_EXPIRED_OR_REVOKED",
    "Share not found": "SHARE_NOT_FOUND",
    "Variant not found": "VARIANT_NOT_FOUND",
    "Verified answer not found": "VERIFIED_ANSWER_NOT_FOUND",
    "Webhook not found": "WEBHOOK_NOT_FOUND",
    "Workflow not found": "WORKFLOW_NOT_FOUND",
    "from must be less than or equal to to": "FROM_MUST_BE_LESS_THAN_OR_EQUAL_TO_TO",
    "profile_id must be a valid UUID": "PROFILE_ID_MUST_BE_A_VALID_UUID",
}

STATUS_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    501: "NOT_IMPLEMENTED",
    503: "SERVICE_UNAVAILABLE",
}


def _status_fallback(status_code: int) -> str:
    code = STATUS_ERROR_CODES.get(status_code)
    if code is not None:
        return code
    if status_code >= 500:
        return "INTERNAL_ERROR"
    if status_code >= 400:
        return "BAD_REQUEST"
    return "ERROR"


def code_for(status_code: int, detail: Any) -> str:
    """Return the UPPER_SNAKE error code for a status and ``detail`` value."""
    if isinstance(detail, dict):
        for key in ("code", "error"):
            candidate = detail.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    elif isinstance(detail, str):
        mapped = DETAIL_ERROR_CODES.get(detail)
        if mapped is not None:
            return mapped
    return _status_fallback(status_code)
