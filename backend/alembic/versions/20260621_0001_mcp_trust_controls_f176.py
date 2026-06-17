"""MCP trust and exposure controls (F176)

Revision ID: 20260621_0001
Revises: 20260620_0002
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260621_0001"
down_revision = "20260620_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "org_mcp_policies",
        sa.Column("allowed_resources", sa.JSON(), nullable=True),
    )
    op.add_column(
        "org_mcp_policies",
        sa.Column("allowed_prompts", sa.JSON(), nullable=True),
    )
    op.add_column(
        "org_mcp_policies",
        sa.Column("allowed_collections", sa.JSON(), nullable=True),
    )
    op.add_column(
        "org_mcp_policies",
        sa.Column("allowed_roles", sa.JSON(), nullable=True),
    )
    op.add_column(
        "org_mcp_policies",
        sa.Column(
            "redact_document_text",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "org_mcp_policies",
        sa.Column("max_chunk_chars", sa.Integer(), nullable=True),
    )
    op.add_column(
        "org_mcp_policies",
        sa.Column("max_request_bytes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "org_mcp_policies",
        sa.Column("max_response_bytes", sa.Integer(), nullable=True),
    )

    op.create_check_constraint(
        "mcp_trust_max_chunk_chars_min",
        "org_mcp_policies",
        "max_chunk_chars IS NULL OR max_chunk_chars >= 100",
    )
    op.create_check_constraint(
        "mcp_trust_max_request_bytes_min",
        "org_mcp_policies",
        "max_request_bytes IS NULL OR max_request_bytes >= 256",
    )
    op.create_check_constraint(
        "mcp_trust_max_response_bytes_min",
        "org_mcp_policies",
        "max_response_bytes IS NULL OR max_response_bytes >= 256",
    )


def downgrade() -> None:
    op.drop_constraint("mcp_trust_max_response_bytes_min", "org_mcp_policies", type_="check")
    op.drop_constraint("mcp_trust_max_request_bytes_min", "org_mcp_policies", type_="check")
    op.drop_constraint("mcp_trust_max_chunk_chars_min", "org_mcp_policies", type_="check")
    op.drop_column("org_mcp_policies", "max_response_bytes")
    op.drop_column("org_mcp_policies", "max_request_bytes")
    op.drop_column("org_mcp_policies", "max_chunk_chars")
    op.drop_column("org_mcp_policies", "redact_document_text")
    op.drop_column("org_mcp_policies", "allowed_roles")
    op.drop_column("org_mcp_policies", "allowed_collections")
    op.drop_column("org_mcp_policies", "allowed_prompts")
    op.drop_column("org_mcp_policies", "allowed_resources")
