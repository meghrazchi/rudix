"""Provider security and governance controls (F225)

Extends organization_governance_policies with five new columns that control
provider routing boundaries:
  - local_only_mode          guarantee no cloud provider is ever contacted
  - cloud_fallback_allowed   whether a local→cloud fallback is permitted
  - allowed_provider_profiles JSON list of allowed provider keys (empty = all)
  - admin_only_model_selection  regular users cannot override provider
  - retention_warning_acknowledged  admin has acknowledged logging warnings

Revision ID: 20260609_0003
Revises: 20260609_0002
Create Date: 2026-06-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260609_0003"
down_revision: str | None = "20260609_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_governance_policies",
        sa.Column(
            "local_only_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "organization_governance_policies",
        sa.Column(
            "cloud_fallback_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "organization_governance_policies",
        sa.Column(
            "allowed_provider_profiles",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "organization_governance_policies",
        sa.Column(
            "admin_only_model_selection",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "organization_governance_policies",
        sa.Column(
            "retention_warning_acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("organization_governance_policies", "retention_warning_acknowledged")
    op.drop_column("organization_governance_policies", "admin_only_model_selection")
    op.drop_column("organization_governance_policies", "allowed_provider_profiles")
    op.drop_column("organization_governance_policies", "cloud_fallback_allowed")
    op.drop_column("organization_governance_policies", "local_only_mode")
