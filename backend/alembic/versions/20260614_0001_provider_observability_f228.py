"""Provider observability fields on usage_events (F228)

Adds provider-level metadata columns to usage_events so that per-provider
health, latency, retry, timeout, fallback, and error metrics can be
aggregated without exposing prompt text or retrieved context.

usage_events:
  provider_key  – provider identifier ("openai", "local", etc.)
  profile_name  – task profile name ("chat", "summarization", etc.)
  task_type     – high-level task category ("chat", "pipeline", etc.)
  retry_count   – number of retries attempted (0 = first-attempt success)
  timed_out     – true when the request exceeded the configured timeout
  fallback_used – true when a fallback provider was used
  error_code    – safe error code string; never raw exception messages
  request_id    – correlation ID for support / debugging

New index:
  idx_usage_org_provider_created – speeds up per-provider aggregations

Revision ID: 20260614_0001
Revises: 20260613_0003
Create Date: 2026-06-14 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260614_0001"
down_revision = "20260613_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usage_events", sa.Column("provider_key", sa.String(64), nullable=True))
    op.add_column("usage_events", sa.Column("profile_name", sa.String(64), nullable=True))
    op.add_column("usage_events", sa.Column("task_type", sa.String(64), nullable=True))
    op.add_column("usage_events", sa.Column("retry_count", sa.Integer(), nullable=True))
    op.add_column(
        "usage_events",
        sa.Column("timed_out", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "usage_events",
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("usage_events", sa.Column("error_code", sa.String(64), nullable=True))
    op.add_column("usage_events", sa.Column("request_id", sa.String(128), nullable=True))

    op.create_check_constraint(
        "usage_events_retry_count_non_negative",
        "usage_events",
        "retry_count IS NULL OR retry_count >= 0",
    )
    op.create_index(
        "idx_usage_org_provider_created",
        "usage_events",
        ["organization_id", "provider_key", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_usage_org_provider_created", table_name="usage_events")
    op.drop_constraint("usage_events_retry_count_non_negative", "usage_events", type_="check")
    op.drop_column("usage_events", "request_id")
    op.drop_column("usage_events", "error_code")
    op.drop_column("usage_events", "fallback_used")
    op.drop_column("usage_events", "timed_out")
    op.drop_column("usage_events", "retry_count")
    op.drop_column("usage_events", "task_type")
    op.drop_column("usage_events", "profile_name")
    op.drop_column("usage_events", "provider_key")
