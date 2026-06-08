from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class BillingPlanStatus(StrEnum):
    active = "active"
    trialing = "trialing"
    past_due = "past_due"
    cancelled = "cancelled"
    free = "free"
    self_hosted = "self_hosted"
    unknown = "unknown"


class BillingCycle(StrEnum):
    monthly = "monthly"
    annual = "annual"


class BillingDateRange(StrEnum):
    seven_days = "7d"
    thirty_days = "30d"
    ninety_days = "90d"
    billing_period = "billing_period"


class BillingPlanInfo(BaseModel):
    plan_name: str
    status: BillingPlanStatus
    billing_cycle: BillingCycle | None
    renewal_date: datetime | None
    trial_end_date: datetime | None
    seats_used: int | None
    seats_included: int | None
    storage_used_gb: float | None
    storage_included_gb: float | None
    monthly_questions_used: int | None
    monthly_questions_included: int | None
    token_allowance_used: int | None
    token_allowance_included: int | None
    evaluation_allowance_used: int | None
    evaluation_allowance_included: int | None
    agent_allowance_used: int | None
    agent_allowance_included: int | None
    connector_allowance_used: int | None
    connector_allowance_included: int | None
    can_manage_subscription: bool
    can_cancel_plan: bool


class BillingUsageSummary(BaseModel):
    range: dict[str, str]
    documents_uploaded: int | None
    indexed_documents: int | None
    storage_used_gb: float | None
    total_chunks: int | None
    questions_asked: int | None
    avg_confidence: float | None
    avg_latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_llm_cost_usd: float | None
    evaluation_runs: int | None
    agent_runs: int | None
    connector_sync_jobs: int | None
    failed_indexing_jobs: int | None


class BillingQuota(BaseModel):
    resource: str
    label: str
    used: float
    limit: float | None
    unit: str


class InvoiceStatus(StrEnum):
    paid = "paid"
    open = "open"
    void = "void"
    uncollectible = "uncollectible"


class Invoice(BaseModel):
    id: str
    date: datetime
    amount_usd: float
    status: InvoiceStatus
    download_url: str | None


class BillingContact(BaseModel):
    email: str | None = None
    name: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    tax_id: str | None = None
    payment_method_summary: str | None = None


class BillingContactUpdateRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=255)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=64)
    tax_id: str | None = Field(default=None, max_length=64)
    payment_method_summary: str | None = None


class BillingPortalSession(BaseModel):
    url: str
    expires_at: datetime | None

