"""connector platform foundation

Revision ID: 20260605_0008
Revises: 20260605_0007
Create Date: 2026-06-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260605_0008"
down_revision: str | None = "20260605_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_providers",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("auth_type", sa.String(32), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("config_schema", sa.JSON(), nullable=False),
        sa.Column("rate_limits", sa.JSON(), nullable=False),
        sa.Column("export_formats", sa.JSON(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            "auth_type IN ('none', 'oauth2', 'api_token', 'service_account', 'basic')",
            name="connector_providers_auth_type_allowed",
        ),
        sa.CheckConstraint(
            "length(trim(key)) >= 1",
            name="connector_providers_key_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_providers")),
        sa.UniqueConstraint("key", name="uq_connector_providers_key"),
    )

    op.create_table(
        "connector_connections",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("external_account_id", sa.String(512), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("auth_config", sa.JSON(), nullable=False),
        sa.Column("sync_cursor", sa.JSON(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            "status IN ('active', 'disabled', 'error', 'revoked')",
            name="connector_connections_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_connector_connections_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["connector_providers.id"],
            name=op.f("fk_connector_connections_provider_id_connector_providers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_connector_connections_collection_id_collections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_connector_connections_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_connections")),
        sa.UniqueConstraint(
            "organization_id",
            "provider_id",
            "external_account_id",
            "collection_id",
            name="uq_connector_connections_org_provider_account_collection",
        ),
    )
    op.create_index(
        "idx_connector_connections_org_provider",
        "connector_connections",
        ["organization_id", "provider_id"],
    )
    op.create_index(
        "idx_connector_connections_collection_id",
        "connector_connections",
        ["collection_id"],
    )

    op.create_table(
        "external_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("provider_source_id", sa.String(1024), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("sync_cursor", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_external_sources_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            name=op.f("fk_external_sources_connection_id_connector_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_external_sources_collection_id_collections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_sources")),
        sa.UniqueConstraint(
            "organization_id",
            "connection_id",
            "provider_source_id",
            name="uq_external_sources_org_connection_provider_source",
        ),
    )
    op.create_index(
        "idx_external_sources_org_connection",
        "external_sources",
        ["organization_id", "connection_id"],
    )
    op.create_index(
        "idx_external_sources_collection_id",
        "external_sources",
        ["collection_id"],
    )

    op.create_table(
        "external_items",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_source_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("provider_item_id", sa.String(1024), nullable=False),
        sa.Column("provider_parent_id", sa.String(1024), nullable=True),
        sa.Column("root_provider_item_id", sa.String(1024), nullable=True),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sync_version", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("acl_hash", sa.String(128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
            "item_type IN ('issue', 'wiki_page', 'cloud_file', 'folder', 'comment', 'attachment')",
            name="external_items_item_type_allowed",
        ),
        sa.CheckConstraint(
            "visibility IN ('org_wide', 'collection', 'restricted')",
            name="external_items_visibility_allowed",
        ),
        sa.CheckConstraint(
            "length(trim(provider_item_id)) >= 1",
            name="external_items_id_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(source_url)) >= 1",
            name="external_items_url_not_blank",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="external_items_content_hash_length",
        ),
        sa.CheckConstraint(
            "sync_version >= 1",
            name="external_items_sync_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_external_items_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            name=op.f("fk_external_items_connection_id_connector_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_source_id"],
            ["external_sources.id"],
            name=op.f("fk_external_items_external_source_id_external_sources"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_external_items_collection_id_collections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_items")),
        sa.UniqueConstraint(
            "organization_id",
            "connection_id",
            "provider_item_id",
            name="uq_external_items_org_connection_provider_item",
        ),
    )
    op.create_index(
        "idx_external_items_org_type", "external_items", ["organization_id", "item_type"]
    )
    op.create_index("idx_external_items_source", "external_items", ["external_source_id"])
    op.create_index("idx_external_items_collection_id", "external_items", ["collection_id"])
    op.create_index(
        "idx_external_items_parent",
        "external_items",
        ["organization_id", "provider_parent_id"],
    )
    op.create_index(
        "idx_external_items_hash", "external_items", ["organization_id", "content_hash"]
    )

    op.create_table(
        "connector_sync_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_source_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("cursor", sa.JSON(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            "status IN ('active', 'paused', 'disabled')",
            name="connector_sync_jobs_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_connector_sync_jobs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            name=op.f("fk_connector_sync_jobs_connection_id_connector_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_source_id"],
            ["external_sources.id"],
            name=op.f("fk_connector_sync_jobs_external_source_id_external_sources"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_connector_sync_jobs_collection_id_collections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_sync_jobs")),
    )
    op.create_index(
        "idx_connector_sync_jobs_org_status",
        "connector_sync_jobs",
        ["organization_id", "status"],
    )
    op.create_index(
        "idx_connector_sync_jobs_connection_id",
        "connector_sync_jobs",
        ["connection_id"],
    )
    op.create_index(
        "idx_connector_sync_jobs_source_id",
        "connector_sync_jobs",
        ["external_source_id"],
    )

    op.create_table(
        "connector_sync_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sync_job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_source_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sync_version", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("items_seen", sa.Integer(), nullable=False),
        sa.Column("items_upserted", sa.Integer(), nullable=False),
        sa.Column("items_deleted", sa.Integer(), nullable=False),
        sa.Column("cursor_before", sa.JSON(), nullable=False),
        sa.Column("cursor_after", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False),
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
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="connector_sync_runs_status_allowed",
        ),
        sa.CheckConstraint(
            "items_seen >= 0",
            name="connector_sync_runs_items_seen_non_negative",
        ),
        sa.CheckConstraint(
            "items_upserted >= 0",
            name="connector_sync_runs_upserted_non_negative",
        ),
        sa.CheckConstraint(
            "items_deleted >= 0",
            name="connector_sync_runs_deleted_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_connector_sync_runs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_job_id"],
            ["connector_sync_jobs.id"],
            name=op.f("fk_connector_sync_runs_sync_job_id_connector_sync_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            name=op.f("fk_connector_sync_runs_connection_id_connector_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_source_id"],
            ["external_sources.id"],
            name=op.f("fk_connector_sync_runs_external_source_id_external_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_sync_runs")),
    )
    op.create_index(
        "idx_connector_sync_runs_org_status",
        "connector_sync_runs",
        ["organization_id", "status"],
    )
    op.create_index(
        "idx_connector_sync_runs_job_created",
        "connector_sync_runs",
        ["sync_job_id", "created_at"],
    )

    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("collection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("sync_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("sync_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
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
            "length(content_hash) = 64",
            name="source_documents_content_hash_length",
        ),
        sa.CheckConstraint(
            "sync_version >= 1",
            name="source_documents_sync_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_source_documents_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_item_id"],
            ["external_items.id"],
            name=op.f("fk_source_documents_external_item_id_external_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_source_documents_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_source_documents_collection_id_collections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["connector_sync_runs.id"],
            name=op.f("fk_source_documents_sync_run_id_connector_sync_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_documents")),
        sa.UniqueConstraint(
            "external_item_id",
            "document_id",
            name="uq_source_documents_external_item_document",
        ),
    )
    op.create_index(
        "idx_source_documents_org_document",
        "source_documents",
        ["organization_id", "document_id"],
    )
    op.create_index(
        "idx_source_documents_external_item",
        "source_documents",
        ["external_item_id"],
    )
    op.create_index(
        "idx_source_documents_collection_id",
        "source_documents",
        ["collection_id"],
    )

    op.create_table(
        "source_references",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("reference_type", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(1024), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
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
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_source_references_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name=op.f("fk_source_references_source_document_id_source_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_item_id"],
            ["external_items.id"],
            name=op.f("fk_source_references_external_item_id_external_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_source_references_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_source_references_chunk_id_document_chunks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_references")),
    )
    op.create_index(
        "idx_source_references_org_document",
        "source_references",
        ["organization_id", "document_id"],
    )
    op.create_index(
        "idx_source_references_external_item",
        "source_references",
        ["external_item_id"],
    )
    op.create_index(
        "idx_source_references_chunk_id",
        "source_references",
        ["chunk_id"],
    )

    op.create_table(
        "external_item_tombstones",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("external_source_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("sync_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("provider_item_id", sa.String(1024), nullable=False),
        sa.Column("item_type", sa.String(32), nullable=True),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_sync_version", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
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
            "item_type IS NULL OR item_type IN ('issue', 'wiki_page', 'cloud_file', 'folder', 'comment', 'attachment')",
            name="external_item_tombstones_item_type_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_external_item_tombstones_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connector_connections.id"],
            name=op.f("fk_external_item_tombstones_connection_id_connector_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["external_source_id"],
            ["external_sources.id"],
            name=op.f("fk_external_item_tombstones_external_source_id_external_sources"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["connector_sync_runs.id"],
            name=op.f("fk_external_item_tombstones_sync_run_id_connector_sync_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_item_tombstones")),
        sa.UniqueConstraint(
            "organization_id",
            "connection_id",
            "provider_item_id",
            name="uq_external_item_tombstones_org_connection_provider_item",
        ),
    )
    op.create_index(
        "idx_external_item_tombstones_org",
        "external_item_tombstones",
        ["organization_id", "tombstoned_at"],
    )
    op.create_index(
        "idx_external_item_tombstones_source",
        "external_item_tombstones",
        ["external_source_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_external_item_tombstones_source", table_name="external_item_tombstones")
    op.drop_index("idx_external_item_tombstones_org", table_name="external_item_tombstones")
    op.drop_table("external_item_tombstones")

    op.drop_index("idx_source_references_chunk_id", table_name="source_references")
    op.drop_index("idx_source_references_external_item", table_name="source_references")
    op.drop_index("idx_source_references_org_document", table_name="source_references")
    op.drop_table("source_references")

    op.drop_index("idx_source_documents_collection_id", table_name="source_documents")
    op.drop_index("idx_source_documents_external_item", table_name="source_documents")
    op.drop_index("idx_source_documents_org_document", table_name="source_documents")
    op.drop_table("source_documents")

    op.drop_index("idx_connector_sync_runs_job_created", table_name="connector_sync_runs")
    op.drop_index("idx_connector_sync_runs_org_status", table_name="connector_sync_runs")
    op.drop_table("connector_sync_runs")

    op.drop_index("idx_connector_sync_jobs_source_id", table_name="connector_sync_jobs")
    op.drop_index("idx_connector_sync_jobs_connection_id", table_name="connector_sync_jobs")
    op.drop_index("idx_connector_sync_jobs_org_status", table_name="connector_sync_jobs")
    op.drop_table("connector_sync_jobs")

    op.drop_index("idx_external_items_hash", table_name="external_items")
    op.drop_index("idx_external_items_parent", table_name="external_items")
    op.drop_index("idx_external_items_collection_id", table_name="external_items")
    op.drop_index("idx_external_items_source", table_name="external_items")
    op.drop_index("idx_external_items_org_type", table_name="external_items")
    op.drop_table("external_items")

    op.drop_index("idx_external_sources_collection_id", table_name="external_sources")
    op.drop_index("idx_external_sources_org_connection", table_name="external_sources")
    op.drop_table("external_sources")

    op.drop_index("idx_connector_connections_collection_id", table_name="connector_connections")
    op.drop_index("idx_connector_connections_org_provider", table_name="connector_connections")
    op.drop_table("connector_connections")

    op.drop_table("connector_providers")
