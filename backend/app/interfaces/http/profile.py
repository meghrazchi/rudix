"""
Settings – Profile endpoint stubs.

Contract (F193): These routes define the expected API surface for the Settings
Profile tab.  They return HTTP 501 until the backing service layer is
implemented (tracked in follow-up tickets).  The frontend detects 501 via the
unavailable-endpoint pattern and renders a deployment-controlled state instead.

Auth:   Bearer JWT required (enforced by the parent protected_router).
Org:    All write operations are scoped to principal.organization_id.
Roles:  GET  /me              – any authenticated user
        PATCH /me             – any authenticated user (own record only)
        GET  /me/preferences  – any authenticated user
        PATCH /me/preferences – any authenticated user (own record only)
        POST  /me/sign-out-all – any authenticated user
        DELETE /me            – any authenticated user (own record only; owner
                                accounts require org-transfer first)
Rate:   60 req/min per user on GET; 20 req/min per user on write operations.

Error shape (all 4xx/5xx):
    { "error_code": "<CODE>", "detail": "<human-readable>" }

Error codes used here:
    NOT_IMPLEMENTED – endpoint stub not yet backed by service layer
    UNAUTHORIZED    – missing or invalid JWT (handled by auth middleware)
    FORBIDDEN       – org context missing or wrong role
    UNPROCESSABLE   – validation error on request body
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal

router = APIRouter(prefix="/me", tags=["profile"])

_NOT_IMPLEMENTED = JSONResponse(
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    content={
        "error_code": "NOT_IMPLEMENTED",
        "detail": "This endpoint is not yet implemented. "
        "The frontend will show a deployment-controlled state.",
    },
)


# ── GET /me ───────────────────────────────────────────────────────────────────
# TODO(F193-follow-up): implement UserService.get_me()
# Expected response shape:
# {
#   "id": "<uuid>",
#   "email": "<string>",
#   "name": "<string | null>",
#   "avatar_url": "<string | null>",
#   "created_at": "<ISO-8601 | null>"
# }
@router.get("", status_code=status.HTTP_200_OK)
async def get_me(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── PATCH /me ─────────────────────────────────────────────────────────────────
# TODO(F193-follow-up): implement UserService.update_me()
# Request body: { "name": "<string, 1-120 chars>" }
# Response: same shape as GET /me
@router.patch("", status_code=status.HTTP_200_OK)
async def update_me(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /me/preferences ───────────────────────────────────────────────────────
# TODO(F193-follow-up): implement UserPreferencesService.get_preferences()
# Expected response shape:
# {
#   "language": "<string | null>",
#   "timezone": "<string | null>",
#   "date_format": "<string | null>",
#   "theme": "<'light'|'dark'|'system' | null>",
#   "landing_page": "<string | null>",
#   "keyboard_shortcut_hints": "<boolean | null>",
#   "email_notifications": "<boolean | null>",
#   "digest_frequency": "<'daily'|'weekly'|'never' | null>"
# }
@router.get("/preferences", status_code=status.HTTP_200_OK)
async def get_my_preferences(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── PATCH /me/preferences ─────────────────────────────────────────────────────
# TODO(F193-follow-up): implement UserPreferencesService.update_preferences()
# Request body: partial subset of preference fields (all optional)
# Response: full preference object (same shape as GET /me/preferences)
@router.patch("/preferences", status_code=status.HTTP_200_OK)
async def update_my_preferences(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── POST /me/sign-out-all ─────────────────────────────────────────────────────
# TODO(F193-follow-up): revoke all refresh tokens for the current user
# Response: 204 No Content on success; current access token remains valid until
#           its natural expiry so the user can see the confirmation message.
@router.post("/sign-out-all", status_code=status.HTTP_200_OK)
async def sign_out_all_devices(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── DELETE /me ────────────────────────────────────────────────────────────────
# TODO(F193-follow-up): implement UserService.delete_personal_account()
# Guard: owner accounts must transfer org ownership before self-deletion.
# Response: 204 No Content; session cookies cleared by auth middleware.
# NOTE: must never delete org data — only the user record and personal tokens.
@router.delete("", status_code=status.HTTP_200_OK)
async def delete_personal_account(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED
