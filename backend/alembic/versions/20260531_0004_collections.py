"""knowledge base collections

Revision ID: 20260531_0004
Revises: 20260523_0003
Create Date: 2026-05-31 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260531_0004"
down_revision: str | None = "20260523_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("access_policy", sa.String(32), nullable=False, server_default="org_wide"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            "access_policy IN ('org_wide', 'restricted')",
            name=op.f("ck_collections_collections_access_policy_allowed"),
        ),
        sa.CheckConstraint(
            "char_length(trim(name)) >= 1",
            name=op.f("ck_collections_collections_name_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_collections_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_collections_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collections")),
    )
    op.create_index("idx_collections_org_id", "collections", ["organization_id"])
    op.create_index("idx_collections_owner_id", "collections", ["owner_id"])

    op.create_table(
        "collection_documents",
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_collection_documents_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_collection_documents_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("collection_id", "document_id", name=op.f("pk_collection_documents")),
        sa.UniqueConstraint(
            "collection_id",
            "document_id",
            name="uq_collection_documents_pair",
        ),
    )
    op.create_index(
        "idx_collection_documents_collection_id", "collection_documents", ["collection_id"]
    )
    op.create_index(
        "idx_collection_documents_document_id", "collection_documents", ["document_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_collection_documents_document_id", table_name="collection_documents")
    op.drop_index("idx_collection_documents_collection_id", table_name="collection_documents")
    op.drop_table("collection_documents")
    op.drop_index("idx_collections_owner_id", table_name="collections")
    op.drop_index("idx_collections_org_id", table_name="collections")
    op.drop_table("collections")
