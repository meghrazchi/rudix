"""contact submissions for public contact form.

Revision ID: 20260701_0002
Revises: 20260701_0001
Create Date: 2026-07-01

Stores validated public contact form submissions and the corresponding email
dispatch status. CAPTCHA tokens and honeypot values are intentionally not
persisted.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260701_0002"
down_revision: str | None = "20260701_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_submissions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("full_name", sa.String(100), nullable=False),
        sa.Column("work_email", sa.String(255), nullable=False),
        sa.Column("company", sa.String(120), nullable=False),
        sa.Column("role_title", sa.String(120), nullable=False),
        sa.Column("use_case", sa.String(160), nullable=False),
        sa.Column("team_size", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("consent_accepted", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("receiver_email", sa.String(255), nullable=True),
        sa.Column("email_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("email_provider", sa.String(32), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("email_error", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("ip_address", sa.String(128), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
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
        sa.CheckConstraint(
            "email_status IN ('pending', 'sent', 'failed', 'skipped')",
            name="contact_submissions_email_status_allowed",
        ),
    )
    op.create_index(
        "idx_contact_submissions_created",
        "contact_submissions",
        ["created_at"],
    )
    op.create_index(
        "idx_contact_submissions_email_status",
        "contact_submissions",
        ["email_status", "created_at"],
    )
    op.create_index(
        "idx_contact_submissions_work_email",
        "contact_submissions",
        ["work_email"],
    )


def downgrade() -> None:
    op.drop_index("idx_contact_submissions_work_email", table_name="contact_submissions")
    op.drop_index("idx_contact_submissions_email_status", table_name="contact_submissions")
    op.drop_index("idx_contact_submissions_created", table_name="contact_submissions")
    op.drop_table("contact_submissions")
