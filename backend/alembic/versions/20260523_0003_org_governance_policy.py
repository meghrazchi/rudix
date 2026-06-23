"""organization governance policy persistence

Revision ID: 20260523_0003
Revises: 20260520_0002
Create Date: 2026-05-23 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260523_0003"
down_revision: str | None = "20260520_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_governance_policies",
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "agentic_mode_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "mcp_exposure_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "allow_side_effect_tools",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "allowed_tool_names", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("max_steps", sa.Integer(), nullable=True),
        sa.Column("max_tool_calls_per_run", sa.Integer(), nullable=True),
        sa.Column("max_tool_timeout_ms", sa.Integer(), nullable=True),
        sa.Column("max_tool_input_bytes", sa.Integer(), nullable=True),
        sa.Column("max_tool_output_bytes", sa.Integer(), nullable=True),
        sa.Column("max_tool_retry_attempts", sa.Integer(), nullable=True),
        sa.Column("max_total_tokens", sa.Integer(), nullable=True),
        sa.Column("max_total_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            "external_mcp_servers", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "max_steps IS NULL OR max_steps >= 1",
            name=op.f("ck_organization_governance_policies_org_governance_max_steps_positive"),
        ),
        sa.CheckConstraint(
            "max_tool_calls_per_run IS NULL OR max_tool_calls_per_run >= 1",
            name=op.f("ck_organization_governance_policies_org_governance_max_tool_calls_positive"),
        ),
        sa.CheckConstraint(
            "max_tool_timeout_ms IS NULL OR max_tool_timeout_ms >= 100",
            name=op.f("ck_organization_governance_policies_org_governance_timeout_min"),
        ),
        sa.CheckConstraint(
            "max_tool_input_bytes IS NULL OR max_tool_input_bytes >= 512",
            name=op.f("ck_organization_governance_policies_org_governance_input_bytes_min"),
        ),
        sa.CheckConstraint(
            "max_tool_output_bytes IS NULL OR max_tool_output_bytes >= 512",
            name=op.f("ck_organization_governance_policies_org_governance_output_bytes_min"),
        ),
        sa.CheckConstraint(
            "max_tool_retry_attempts IS NULL OR max_tool_retry_attempts >= 0",
            name=op.f(
                "ck_organization_governance_policies_org_governance_retry_attempts_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "max_total_tokens IS NULL OR max_total_tokens >= 1",
            name=op.f("ck_organization_governance_policies_org_governance_total_tokens_positive"),
        ),
        sa.CheckConstraint(
            "max_total_cost_usd IS NULL OR max_total_cost_usd >= 0",
            name=op.f("ck_organization_governance_policies_org_governance_total_cost_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_governance_policies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_organization_governance_policies_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_governance_policies")),
    )
    op.create_index(
        "idx_org_governance_org_id",
        "organization_governance_policies",
        ["organization_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_org_governance_org_id", table_name="organization_governance_policies")
    op.drop_table("organization_governance_policies")
