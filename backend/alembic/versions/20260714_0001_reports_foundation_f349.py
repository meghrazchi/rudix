"""reports data model and indexes for F349.

Revision ID: 20260714_0001
Revises: 20260701_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0001"
down_revision: str | None = "20260701_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("connector_id", sa.Uuid(as_uuid=True), sa.ForeignKey("connector_connections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("team_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_id", sa.Uuid(as_uuid=True), sa.ForeignKey("external_sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("count >= 0", name="report_events_count_non_negative"),
        sa.CheckConstraint("value IS NULL OR value >= 0", name="report_events_value_non_negative"),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="report_events_duration_non_negative"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_report_events_org_idempotency"),
    )
    for name, columns in (
        ("idx_report_events_org_occurred", ["organization_id", "occurred_at"]),
        ("idx_report_events_org_category_occurred", ["organization_id", "category", "occurred_at"]),
        ("idx_report_events_org_user_occurred", ["organization_id", "user_id", "occurred_at"]),
        ("idx_report_events_org_collection_occurred", ["organization_id", "collection_id", "occurred_at"]),
        ("idx_report_events_org_connector_occurred", ["organization_id", "connector_id", "occurred_at"]),
        ("idx_report_events_org_source_occurred", ["organization_id", "source_id", "occurred_at"]),
    ):
        op.create_index(name, "report_events", columns)


def downgrade() -> None:
    op.drop_table("report_events")
