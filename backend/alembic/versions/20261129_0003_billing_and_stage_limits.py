"""billing tables and plan stage limits (R09-03, R09-09 schema, 0.9.0 S1)

Revision ID: 20261129_0003
Revises: 20261129_0002
Create Date: 2026-11-29 00:00:02.000000

Adds:

- ``billing_plans``: global plan catalogue (quota limits, stage limits, provider price ids,
  display prices). No tenant column.
- ``billing_customers``, ``billing_subscriptions``, ``billing_invoices``: provider objects per
  organisation, unique on ``(provider, provider_<object>_id)``.
- ``billing_webhook_events``: one row per provider event, unique on ``(provider, event_id)``
  (deduplication); only a SHA-256 of the payload is kept.
- ``org_quota_policy.stage_limits`` (nullable JSON): NULL means every optional pipeline stage
  is allowed, which is the behaviour before 0.9.0.

Data-safety notes:
- Additive only: five new, empty tables and one nullable column on a small table. Every
  statement runs after ``SET LOCAL lock_timeout = '5s'``.
- Row-level security from literal lists (``tests/test_rls_coverage.py`` checks them against
  ``RLS_LOOKUP_TABLES_0_9_0`` and ``RLS_STRICT_TABLES_0_9_0``): customers, subscriptions, and
  webhook events are read by the webhook handler before a tenant is bound (lookup policy);
  invoices are only read inside a tenant (strict policy).

Rollback:
- ``downgrade`` drops the policies, the five tables, and ``org_quota_policy.stage_limits``.
  All billing state (customer and subscription links, invoices, webhook history, the plan
  catalogue) and every plan stage limit is lost; the provider still holds the subscriptions,
  and a re-upgrade needs the reconciliation job to restore them. Run it only before any
  production use of billing.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.rls import (
    TENANT_RLS_POLICY_NAME,
    build_lookup_policy_sql,
    build_strict_policy_sql,
)

revision: str = "20261129_0003"
down_revision: str | None = "20261129_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LOOKUP_TABLES: tuple[str, ...] = (
    "billing_customers",
    "billing_subscriptions",
    "billing_webhook_events",
)
STRICT_TABLES: tuple[str, ...] = ("billing_invoices",)

SUBSCRIPTION_STATUSES: tuple[str, ...] = (
    "incomplete",
    "incomplete_expired",
    "trialing",
    "active",
    "past_due",
    "canceled",
    "unpaid",
    "paused",
)
WEBHOOK_EVENT_STATUSES: tuple[str, ...] = ("received", "processed", "ignored", "failed")


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _org_column(*, nullable: bool = False, ondelete: str = "CASCADE") -> sa.Column:
    return sa.Column(
        "organization_id",
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete=ondelete),
        nullable=nullable,
    )


def _json_object(name: str) -> sa.Column:
    return sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text("'{}'"))


def _create_plans_and_customers() -> None:
    op.create_table(
        "billing_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("plan_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        _json_object("quota_limits"),
        sa.Column("stage_limits", sa.JSON(), nullable=True),
        _json_object("provider_prices"),
        _json_object("display_prices"),
        *_timestamps(),
        sa.UniqueConstraint("plan_key", name="uq_billing_plans_plan_key"),
    )
    op.create_table(
        "billing_customers",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        _org_column(),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_customer_id", sa.String(length=255), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", name="uq_billing_customers_organization_id"),
        sa.UniqueConstraint(
            "provider", "provider_customer_id", name="uq_billing_customers_provider_customer"
        ),
    )


def _create_subscriptions_and_invoices() -> None:
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        _org_column(),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("plan_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("billing_interval", sa.String(length=8), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "provider",
            "provider_subscription_id",
            name="uq_billing_subscriptions_provider_subscription",
        ),
        sa.CheckConstraint(
            _in_list("status", SUBSCRIPTION_STATUSES),
            name=op.f("ck_billing_subscriptions_status_allowed"),
        ),
    )
    op.create_index("idx_billing_subscriptions_org", "billing_subscriptions", ["organization_id"])
    op.create_table(
        "billing_invoices",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        _org_column(),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_invoice_id", sa.String(length=255), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_due_minor", sa.BigInteger(), nullable=False),
        sa.Column("amount_paid_minor", sa.BigInteger(), nullable=False),
        sa.Column("hosted_invoice_url", sa.String(length=2048), nullable=True),
        sa.Column("invoice_pdf_url", sa.String(length=2048), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "provider", "provider_invoice_id", name="uq_billing_invoices_provider_invoice"
        ),
    )
    op.create_index(
        "idx_billing_invoices_org_issued", "billing_invoices", ["organization_id", "issued_at"]
    )


def _create_webhook_events() -> None:
    op.create_table(
        "billing_webhook_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("event_created_at", sa.DateTime(timezone=True), nullable=False),
        _org_column(nullable=True, ondelete="SET NULL"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "provider", "event_id", name="uq_billing_webhook_events_provider_event"
        ),
        sa.CheckConstraint(
            _in_list("status", WEBHOOK_EVENT_STATUSES),
            name=op.f("ck_billing_webhook_events_status_allowed"),
        ),
    )


def upgrade() -> None:
    if _is_postgresql():
        op.execute("SET LOCAL lock_timeout = '5s'")
    _create_plans_and_customers()
    _create_subscriptions_and_invoices()
    _create_webhook_events()
    op.add_column("org_quota_policy", sa.Column("stage_limits", sa.JSON(), nullable=True))
    if _is_postgresql():
        for table in LOOKUP_TABLES:
            for statement in build_lookup_policy_sql(table):
                op.execute(statement)
        for table in STRICT_TABLES:
            for statement in build_strict_policy_sql(table):
                op.execute(statement)


def downgrade() -> None:
    if _is_postgresql():
        op.execute("SET LOCAL lock_timeout = '5s'")
        for table in (*LOOKUP_TABLES, *STRICT_TABLES):
            op.execute(f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON {table}")
    op.drop_column("org_quota_policy", "stage_limits")
    op.drop_table("billing_webhook_events")
    op.drop_index("idx_billing_invoices_org_issued", table_name="billing_invoices")
    op.drop_table("billing_invoices")
    op.drop_index("idx_billing_subscriptions_org", table_name="billing_subscriptions")
    op.drop_table("billing_subscriptions")
    op.drop_table("billing_customers")
    op.drop_table("billing_plans")
