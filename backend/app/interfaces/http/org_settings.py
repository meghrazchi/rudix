"""
Settings – Organization endpoint stubs.

Contract (F193): These routes define the expected API surface for the Settings
Organization tab.  They return HTTP 501 until the backing service layer is
implemented.  The frontend detects 501 via the unavailable-endpoint pattern.

Auth:   Bearer JWT required (enforced by the parent protected_router).
Org:    All endpoints scoped to principal.organization_id.
Roles:  GET  /organization              – any authenticated member
        PATCH /organization             – owner, admin
        GET  /organization/settings     – owner, admin
        PATCH /organization/settings    – owner, admin
        GET  /organization/ingestion    – owner, admin
        PATCH /organization/ingestion   – owner, admin
Rate:   30 req/min per org on GETs; 10 req/min per org on PATCHes.

Error shape:
    { "error_code": "<CODE>", "detail": "<human-readable>" }

Error codes:
    NOT_IMPLEMENTED – endpoint stub not yet backed by service layer
    FORBIDDEN       – role insufficient for the operation
    CONFLICT        – slug already taken (PATCH /organization)
    UNPROCESSABLE   – validation error on request body
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal

router = APIRouter(prefix="/organization", tags=["organization"])

_NOT_IMPLEMENTED = JSONResponse(
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    content={
        "error_code": "NOT_IMPLEMENTED",
        "detail": "This endpoint is not yet implemented. "
        "The frontend will show a deployment-controlled state.",
    },
)


# ── GET /organization ─────────────────────────────────────────────────────────
# TODO(F193-follow-up): implement OrganizationService.get_profile()
# Expected response shape:
# {
#   "id": "<uuid>",
#   "name": "<string>",
#   "slug": "<string>",
#   "primary_domain": "<string | null>",
#   "domain_allowlist": ["<string>"],
#   "support_email": "<string | null>",
#   "description": "<string | null>",
#   "created_at": "<ISO-8601 | null>",
#   "plan": "<string | null>"
# }
@router.get("", status_code=status.HTTP_200_OK)
async def get_organization(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── PATCH /organization ───────────────────────────────────────────────────────
# TODO(F193-follow-up): implement OrganizationService.update_profile() (owner/admin)
# Request body (all fields optional):
# {
#   "name": "<string, 1-120>",
#   "slug": "<string, 3-40, [a-z0-9-]>",
#   "primary_domain": "<string | null>",
#   "support_email": "<email | null>",
#   "description": "<string, max 500 | null>"
# }
# Validation: slug must be globally unique; returns 409 CONFLICT if taken.
# Response: same shape as GET /organization
@router.patch("", status_code=status.HTTP_200_OK)
async def update_organization(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /organization/settings ────────────────────────────────────────────────
# TODO(F193-follow-up): implement OrganizationService.get_settings() (owner/admin)
# Expected response shape:
# {
#   "default_member_role": "<'member'|'viewer'>",
#   "invite_only": "<boolean>",
#   "allowed_email_domains": ["<string>"],
#   "default_document_visibility": "<'public'|'private'>",
#   "default_collection": "<uuid | null>",
#   "retention_days": "<integer | null>",
#   "source_download": "<'all'|'admins'|'none'>",
#   "evaluation_access": "<boolean>",
#   "agentic_access": "<boolean>",
#   "mcp_access": "<boolean>"
# }
@router.get("/settings", status_code=status.HTTP_200_OK)
async def get_organization_settings(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── PATCH /organization/settings ──────────────────────────────────────────────
# TODO(F193-follow-up): implement OrganizationService.update_settings() (owner/admin)
# Request body: partial subset of settings fields (all optional)
# Response: full settings object (same shape as GET /organization/settings)
# Validation: retention_days must be ≥ 1 if present; allowed_email_domains
#             entries must be valid domain names.
@router.patch("/settings", status_code=status.HTTP_200_OK)
async def update_organization_settings(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /organization/ingestion ───────────────────────────────────────────────
# TODO(F193-follow-up): implement OrganizationService.get_ingestion_defaults() (owner/admin)
# Expected response shape:
# {
#   "allowed_file_types": ["<string>"],
#   "max_upload_size_mb": "<integer | null>",
#   "max_page_count": "<integer | null>",
#   "duplicate_handling": "<'allow'|'skip'|'replace'>",
#   "auto_index": "<boolean>",
#   "reindex_policy": "<'on_update'|'manual'>",
#   "retry_policy": "<'never'|'once'|'three_times'>",
#   "default_metadata_tags": ["<string>"]
# }
@router.get("/ingestion", status_code=status.HTTP_200_OK)
async def get_ingestion_defaults(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── PATCH /organization/ingestion ─────────────────────────────────────────────
# TODO(F193-follow-up): implement OrganizationService.update_ingestion_defaults() (owner/admin)
# Request body: partial subset of ingestion fields (all optional)
# Response: full ingestion defaults object
# Validation: max_upload_size_mb must be in [1, 500]; max_page_count in [1, 10000].
@router.patch("/ingestion", status_code=status.HTTP_200_OK)
async def update_ingestion_defaults(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED
