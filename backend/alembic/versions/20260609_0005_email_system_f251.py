"""email_system_f251

Revision ID: 20260609_0005
Revises: 20260609_0004
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_0005"
down_revision: str | None = "20260609_0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "email_delivery_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name="fk_email_delivery_logs_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_email_delivery_logs_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_email_delivery_logs"),
        sa.CheckConstraint(
            "event_type IN ('invite_received','upload_failed','upload_indexed',"
            "'connector_sync_failed','billing_warning','quota_warning','security_alert')",
            name="email_delivery_logs_event_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('queued','sent','failed','bounced','unsubscribed')",
            name="email_delivery_logs_status_allowed",
        ),
    )
    op.create_index(
        "idx_email_delivery_org_created",
        "email_delivery_logs",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "idx_email_delivery_user_event",
        "email_delivery_logs",
        ["user_id", "event_type"],
    )
    op.create_index(
        "idx_email_delivery_status",
        "email_delivery_logs",
        ["status", "created_at"],
    )

    op.create_table(
        "user_notification_preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name="fk_user_notification_preferences_organization_id_organizations",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_notification_preferences_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_notification_preferences"),
        sa.CheckConstraint(
            "event_type IN ('invite_received','upload_failed','upload_indexed',"
            "'connector_sync_failed','billing_warning','quota_warning','security_alert')",
            name="user_notif_pref_event_type_allowed",
        ),
    )
    op.create_index(
        "idx_user_notif_pref_user_org_event",
        "user_notification_preferences",
        ["user_id", "organization_id", "event_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_user_notif_pref_user_org_event", table_name="user_notification_preferences")
    op.drop_table("user_notification_preferences")

    op.drop_index("idx_email_delivery_status", table_name="email_delivery_logs")
    op.drop_index("idx_email_delivery_user_event", table_name="email_delivery_logs")
    op.drop_index("idx_email_delivery_org_created", table_name="email_delivery_logs")
    op.drop_table("email_delivery_logs")
