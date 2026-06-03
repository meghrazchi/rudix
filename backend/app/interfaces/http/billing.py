"""
Settings – Billing endpoint stubs.

Contract (F193): These routes define the expected API surface for the Settings
Billing tab.  They return HTTP 501 until the backing service layer is
implemented.  The frontend detects 501 via the unavailable-endpoint pattern.

Auth:   Bearer JWT required (enforced by the parent protected_router).
Org:    All endpoints scoped to principal.organization_id.
Roles:  All billing endpoints require owner role.
Rate:   20 req/min per org on GETs; 5 req/min on writes and portal sessions.

Error shape:
    { "error_code": "<CODE>", "detail": "<human-readable>" }

Error codes:
    NOT_IMPLEMENTED – endpoint stub not yet backed by service layer
    FORBIDDEN       – role insufficient (non-owner)
    PAYMENT_REQUIRED – subscription lapsed or trial expired (future)
    EXTERNAL_ERROR   – upstream billing provider returned an error

IMPORTANT SECURITY NOTE: Billing endpoints must NEVER return raw payment
instrument data (card numbers, bank account details, CVV).  Payment method
summaries (e.g. "Visa ending 4242") are the maximum allowed exposure.
Portal sessions must return a short-lived redirect URL only.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal

router = APIRouter(prefix="/billing", tags=["billing"])

_NOT_IMPLEMENTED = JSONResponse(
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    content={
        "error_code": "NOT_IMPLEMENTED",
        "detail": "This endpoint is not yet implemented. "
        "The frontend will show a deployment-controlled state.",
    },
)


# ── GET /billing/plan ─────────────────────────────────────────────────────────
# TODO(F193-follow-up): implement BillingService.get_plan_info()
# Expected response shape:
# {
#   "plan_name": "<string>",
#   "status": "<'active'|'trialing'|'past_due'|'cancelled'|'unknown'>",
#   "billing_cycle": "<'monthly'|'annual' | null>",
#   "renewal_date": "<ISO-8601 | null>",
#   "trial_end_date": "<ISO-8601 | null>",
#   "seats_used": "<integer | null>",
#   "seats_included": "<integer | null>",
#   "storage_used_gb": "<float | null>",
#   "storage_included_gb": "<float | null>",
#   "monthly_questions_used": "<integer | null>",
#   "monthly_questions_included": "<integer | null>",
#   "token_allowance_used": "<integer | null>",
#   "token_allowance_included": "<integer | null>",
#   "evaluation_allowance_used": "<integer | null>",
#   "evaluation_allowance_included": "<integer | null>",
#   "agent_allowance_used": "<integer | null>",
#   "agent_allowance_included": "<integer | null>",
#   "connector_allowance_used": "<integer | null>",
#   "connector_allowance_included": "<integer | null>",
#   "can_manage_subscription": "<boolean>",
#   "can_cancel_plan": "<boolean>"
# }
@router.get("/plan", status_code=status.HTTP_200_OK)
async def get_billing_plan(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /billing/usage ────────────────────────────────────────────────────────
# TODO(F193-follow-up): implement BillingService.get_usage_summary()
# Query params: range = "7d" | "30d" | "90d" | "billing_period" (default "30d")
# Expected response shape:
# {
#   "range": { "from": "<ISO-8601>", "to": "<ISO-8601>" },
#   "documents_uploaded": "<integer | null>",
#   "indexed_documents": "<integer | null>",
#   "storage_used_gb": "<float | null>",
#   "total_chunks": "<integer | null>",
#   "questions_asked": "<integer | null>",
#   "avg_confidence": "<float | null>",
#   "avg_latency_ms": "<float | null>",
#   "input_tokens": "<integer | null>",
#   "output_tokens": "<integer | null>",
#   "estimated_llm_cost_usd": "<float | null>",
#   "evaluation_runs": "<integer | null>",
#   "agent_runs": "<integer | null>",
#   "connector_sync_jobs": "<integer | null>",
#   "failed_indexing_jobs": "<integer | null>"
# }
# NOTE: estimated_llm_cost_usd is informational only, not a billing charge.
@router.get("/usage", status_code=status.HTTP_200_OK)
async def get_billing_usage(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /billing/quotas ───────────────────────────────────────────────────────
# TODO(F193-follow-up): implement BillingService.get_quotas()
# Expected response shape (array):
# [
#   {
#     "resource": "<string>",
#     "label": "<string>",
#     "used": "<number>",
#     "limit": "<number | null>",
#     "unit": "<string>"
#   }
# ]
@router.get("/quotas", status_code=status.HTTP_200_OK)
async def get_billing_quotas(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /billing/invoices ─────────────────────────────────────────────────────
# TODO(F193-follow-up): implement BillingService.get_invoices()
# Expected response shape (array or paginated wrapper):
# [
#   {
#     "id": "<string>",
#     "date": "<ISO-8601>",
#     "amount_usd": "<float>",
#     "status": "<'paid'|'open'|'void'|'uncollectible'>",
#     "download_url": "<string | null>"
#   }
# ]
# NOTE: download_url must be a short-lived pre-signed URL; never expose
#       permanent billing provider invoice URLs in API responses.
@router.get("/invoices", status_code=status.HTTP_200_OK)
async def get_invoices(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── GET /billing/contact ──────────────────────────────────────────────────────
# TODO(F193-follow-up): implement BillingService.get_billing_contact()
# Expected response shape:
# {
#   "email": "<string | null>",
#   "name": "<string | null>",
#   "address_line1": "<string | null>",
#   "address_line2": "<string | null>",
#   "city": "<string | null>",
#   "state": "<string | null>",
#   "postal_code": "<string | null>",
#   "country": "<string | null>",
#   "tax_id": "<string | null>",
#   "payment_method_summary": "<string | null>"
# }
# SECURITY: payment_method_summary must only contain the masked summary
#           (e.g. "Visa ending 4242"), never raw card data.
@router.get("/contact", status_code=status.HTTP_200_OK)
async def get_billing_contact(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── PATCH /billing/contact ────────────────────────────────────────────────────
# TODO(F193-follow-up): implement BillingService.update_billing_contact()
# Request body: partial subset of billing contact fields (all optional)
# Response: same shape as GET /billing/contact
# NOTE: payment_method_summary is read-only and ignored if sent in request body.
@router.patch("/contact", status_code=status.HTTP_200_OK)
async def update_billing_contact(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED


# ── POST /billing/portal-session ──────────────────────────────────────────────
# TODO(F193-follow-up): implement BillingService.create_portal_session()
# Creates a short-lived billing portal session with the upstream provider.
# Expected response shape:
# {
#   "url": "<string>",
#   "expires_at": "<ISO-8601 | null>"
# }
# SECURITY: url must be a one-time-use redirect.  Do not cache or log it.
#           Expires in ≤ 5 minutes; frontend must redirect immediately.
@router.post("/portal-session", status_code=status.HTTP_200_OK)
async def create_billing_portal_session(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> JSONResponse:
    return _NOT_IMPLEMENTED
