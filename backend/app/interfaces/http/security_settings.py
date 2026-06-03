"""
Settings – Security endpoint stubs.

Contract (F193): These routes define the expected API surface for the Settings
Security tab.  They return HTTP 501 until the backing service layer is
implemented.  The frontend detects 501 via the unavailable-endpoint pattern.

Auth:   Bearer JWT required (enforced by the parent protected_router).
Org:    All endpoints are scoped to principal.organization_id.
Roles:  Sessions / revoke         – any authenticated user (own sessions only)
        Revoke-all                 – any authenticated user
        Login policy GET/PATCH     – owner, admin
        Security posture GET       – any authenticated user (read-only summary)
        Audit events GET           – owner, admin
Rate:   30 req/min per user on session reads; 10 req/min on revoke operations.
        Login policy: 10 req/min per org on writes.

Error shape:
    { "error_code": "<CODE>", "detail": "<human-readable>" }

Error codes:
    NOT_IMPLEMENTED – endpoint stub not yet backed by service layer
    NOT_FOUND       – session ID not found or does not belong to caller
    FORBIDDEN       – role insufficient for the operation
    CONFLICT        – cannot revoke the current session (use logout instead)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal

router = APIRouter(prefix="/security", tags=["security"])

_NOT_IMPLEMENTED = JSONResponse(
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    content={
        "error_code": "NOT_IMPLEMENTED",
        "detail": "This endpoint is not yet implemented. "
        "The frontend will show a deployment-controlled state.",
    },
)


# ── GET /security/sessions ────────────────────────────────────────────────────
# TODO(F193-follow-up): implement SessionService.list_sessions_for_user()
# Expected response shape (array or paginated wrapper):
# {
#   "items": [
#     {
#       "id": "<uuid>",
#       "device": "<string>",
#       "ip_address": "<string | null>",
#       "location": "<string | null>",
#       "created_at": "<ISO-8601 | null>",
#       "last_active_at": "<ISO-8601 | null>",
#       "is_current": "<boolean>"
#     }
#   ]
# }
# NOTE: Must never expose raw tokens or hashed credentials.
@router.get("/sessions", status_code=status.HTTP_200_OK)
async def get_sessions(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── DELETE /security/sessions/{session_id} ────────────────────────────────────
# TODO(F193-follow-up): revoke a specific session by ID
# Guard: caller must own the session; current session revocation returns 409.
# Response: 204 No Content on success.
@router.delete("/sessions/{session_id}", status_code=status.HTTP_200_OK)
async def revoke_session(
    session_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── POST /security/sessions/revoke-all ───────────────────────────────────────
# TODO(F193-follow-up): revoke all sessions except the current one
# Response: { "revoked_count": <integer> }
@router.post("/sessions/revoke-all", status_code=status.HTTP_200_OK)
async def revoke_all_other_sessions(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /security/login-policy ────────────────────────────────────────────────
# TODO(F193-follow-up): fetch org login policy (owner/admin only)
# Expected response shape:
# {
#   "domain_allowlist": ["<string>"],
#   "session_timeout_hours": "<integer | null>",
#   "sso_required": "<boolean>",
#   "invite_only": "<boolean>",
#   "mfa_required": "<boolean>"
# }
@router.get("/login-policy", status_code=status.HTTP_200_OK)
async def get_login_policy(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── PATCH /security/login-policy ─────────────────────────────────────────────
# TODO(F193-follow-up): update org login policy (owner/admin only)
# Request body: partial subset of login policy fields (all optional)
# Response: full login policy object
# Validation: session_timeout_hours must be in [1, 8760]; domain_allowlist
#             entries must be valid domain names.
@router.patch("/login-policy", status_code=status.HTTP_200_OK)
async def update_login_policy(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /security/posture ─────────────────────────────────────────────────────
# TODO(F193-follow-up): return read-only AI safety posture summary
# Expected response shape:
# {
#   "prompt_injection_protection": "<boolean | null>",
#   "citation_validation": "<boolean | null>",
#   "tenant_isolation": "<boolean | null>",
#   "output_validation": "<boolean | null>",
#   "tool_policy_enforced": "<boolean | null>",
#   "last_audit_at": "<ISO-8601 | null>"
# }
# NOTE: null means "unknown / deployment does not report this metric".
#       Must not expose configuration values or internal pipeline state.
@router.get("/posture", status_code=status.HTTP_200_OK)
async def get_security_posture(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /security/audit-events ────────────────────────────────────────────────
# TODO(F193-follow-up): return recent audit events (owner/admin only)
# Query params: limit (default 5, max 50)
# Expected response shape:
# {
#   "items": [
#     {
#       "id": "<uuid>",
#       "event_type": "<string>",
#       "actor_email": "<string | null>",
#       "created_at": "<ISO-8601>",
#       "summary": "<string>"
#     }
#   ],
#   "total": "<integer>"
# }
# NOTE: Must never expose raw document content, prompt text, or PII beyond
#       the acting user's email.  Sanitize before returning.
@router.get("/audit-events", status_code=status.HTTP_200_OK)
async def get_audit_events(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED
