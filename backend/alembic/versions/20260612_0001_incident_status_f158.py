"""incident_status_f158

Revision ID: 20260612_0001
Revises: 20260609_0005
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260612_0001"
down_revision: str | None = "20260609_0005"


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="investigating"),
        sa.Column("severity", sa.String(32), nullable=False, server_default="medium"),
        sa.Column("affected_services", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
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
        ),
        sa.CheckConstraint(
            "status IN ('investigating','identified','monitoring','resolved')",
            name="incidents_status_check",
        ),
        sa.CheckConstraint(
            "severity IN ('critical','high','medium','low')",
            name="incidents_severity_check",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_incidents_org_status", "incidents", ["organization_id", "status"])
    op.create_index("idx_incidents_org_started_at", "incidents", ["organization_id", "started_at"])

    op.create_table(
        "incident_notes",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("incident_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status_change", sa.String(32), nullable=True),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_incident_notes_incident_id", "incident_notes", ["incident_id"])
    op.create_index(
        "idx_incident_notes_org_created",
        "incident_notes",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_incident_notes_org_created", table_name="incident_notes")
    op.drop_index("idx_incident_notes_incident_id", table_name="incident_notes")
    op.drop_table("incident_notes")
    op.drop_index("idx_incidents_org_started_at", table_name="incidents")
    op.drop_index("idx_incidents_org_status", table_name="incidents")
    op.drop_table("incidents")
