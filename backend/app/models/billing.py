"""Billing plans, provider customers, subscriptions, invoices, webhook events (0.9.0, R09-03).

Provider-neutral: every provider object is keyed by ``(provider, provider_<object>_id)``.
``billing_plans`` is a global catalogue (no tenant column). Nothing here stores card data or
provider secrets; ``billing_webhook_events`` keeps only a SHA-256 of the payload.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

BILLING_SUBSCRIPTION_STATUSES: tuple[str, ...] = (
    "incomplete",
    "incomplete_expired",
    "trialing",
    "active",
    "past_due",
    "canceled",
    "unpaid",
    "paused",
)
BILLING_WEBHOOK_EVENT_STATUSES: tuple[str, ...] = ("received", "processed", "ignored", "failed")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class BillingPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_plans"

    plan_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Same shape as ``OrgQuotaPolicy.limits`` and ``.stage_limits``.
    quota_limits: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    stage_limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"stripe": {"month": "price_x", "year": "price_y"}}
    provider_prices: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # {"month": {"amount_minor": 2900, "currency": "usd"}}
    display_prices: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )


class BillingCustomer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_customers"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_customer_id", name="uq_billing_customers_provider_customer"
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)


class BillingSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_subscription_id",
            name="uq_billing_subscriptions_provider_subscription",
        ),
        CheckConstraint(_in_list("status", BILLING_SUBSCRIPTION_STATUSES), name="status_allowed"),
        Index("idx_billing_subscriptions_org", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_subscription_id: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    billing_interval: Mapped[str | None] = mapped_column(String(8), nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Webhook events older than this are ignored (out-of-order delivery).
    last_event_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_invoices"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_invoice_id", name="uq_billing_invoices_provider_invoice"
        ),
        Index("idx_billing_invoices_org_issued", "organization_id", "issued_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_invoice_id: Mapped[str] = mapped_column(String(255), nullable=False)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount_paid_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    hosted_invoice_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    invoice_pdf_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingWebhookEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "billing_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_billing_webhook_events_provider_event"),
        CheckConstraint(_in_list("status", BILLING_WEBHOOK_EVENT_STATUSES), name="status_allowed"),
    )

    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
