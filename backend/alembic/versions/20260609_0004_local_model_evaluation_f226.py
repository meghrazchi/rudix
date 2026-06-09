"""Local model evaluation, benchmark suites, and release gates (F226)

Extends evaluation_runs with three columns that track which provider profile
was used for a run, enabling cloud-baseline vs local-profile vs fallback-profile
comparison reports and release-gate recommendations.

  - model_profile_key  the TaskType key resolved for this run (e.g. "evaluations")
  - provider_type      the provider that serviced the run (e.g. "openai", "local")
  - provider_profile   classification label: cloud_baseline | local_profile | fallback_profile

Revision ID: 20260609_0004
Revises: 20260609_0003
Create Date: 2026-06-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260609_0004"
down_revision: str | None = "20260609_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column("model_profile_key", sa.String(64), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column("provider_type", sa.String(64), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column("provider_profile", sa.String(32), nullable=True),
    )
    op.create_index(
        "idx_evaluation_runs_provider_profile",
        "evaluation_runs",
        ["provider_profile"],
    )


def downgrade() -> None:
    op.drop_index("idx_evaluation_runs_provider_profile", table_name="evaluation_runs")
    op.drop_column("evaluation_runs", "provider_profile")
    op.drop_column("evaluation_runs", "provider_type")
    op.drop_column("evaluation_runs", "model_profile_key")
