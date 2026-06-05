from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ConnectorAuthType,
    ConnectorConnectionStatus,
    ExternalItemType,
    ExternalItemVisibility,
)


class ConnectorProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_providers"
    __table_args__ = (
        UniqueConstraint("key", name="uq_connector_providers_key"),
        CheckConstraint(
            "auth_type IN ('none', 'oauth2', 'api_token', 'service_account', 'basic')",
            name="connector_providers_auth_type_allowed",
        ),
        CheckConstraint("length(trim(key)) >= 1", name="connector_providers_key_not_blank"),
    )

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    auth_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectorAuthType.oauth2.value,
    )
    capabilities_json: Mapped[list] = mapped_column(
        "capabilities", JSON, nullable=False, default=list
    )
    config_schema_json: Mapped[dict] = mapped_column(
        "config_schema", JSON, nullable=False, default=dict
    )
    rate_limits_json: Mapped[list] = mapped_column(
        "rate_limits", JSON, nullable=False, default=list
    )
    export_formats_json: Mapped[list] = mapped_column(
        "export_formats", JSON, nullable=False, default=list
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    connections = relationship("ConnectorConnection", back_populates="provider")


class ConnectorConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_connections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider_id",
            "external_account_id",
            "collection_id",
            name="uq_connector_connections_org_provider_account_collection",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'error', 'revoked')",
            name="connector_connections_status_allowed",
        ),
        Index("idx_connector_connections_org_provider", "organization_id", "provider_id"),
        Index("idx_connector_connections_collection_id", "collection_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_providers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    external_account_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectorConnectionStatus.active.value,
    )
    auth_config_json: Mapped[dict] = mapped_column(
        "auth_config", JSON, nullable=False, default=dict
    )
    sync_cursor_json: Mapped[dict] = mapped_column(
        "sync_cursor", JSON, nullable=False, default=dict
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization = relationship("Organization")
    provider = relationship("ConnectorProvider", back_populates="connections")
    collection = relationship("Collection")
    sources = relationship(
        "ExternalSource",
        back_populates="connection",
        cascade="all, delete-orphan",
    )
    items = relationship("ExternalItem", back_populates="connection")
    sync_jobs = relationship("ConnectorSyncJob", back_populates="connection")


class ExternalSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_sources"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "connection_id",
            "provider_source_id",
            name="uq_external_sources_org_connection_provider_source",
        ),
        Index("idx_external_sources_org_connection", "organization_id", "connection_id"),
        Index("idx_external_sources_collection_id", "collection_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_source_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    sync_cursor_json: Mapped[dict] = mapped_column(
        "sync_cursor", JSON, nullable=False, default=dict
    )
    config_json: Mapped[dict] = mapped_column("config", JSON, nullable=False, default=dict)
    permissions_json: Mapped[dict] = mapped_column(
        "permissions", JSON, nullable=False, default=dict
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organization = relationship("Organization")
    connection = relationship("ConnectorConnection", back_populates="sources")
    collection = relationship("Collection")
    items = relationship("ExternalItem", back_populates="external_source")
    sync_jobs = relationship("ConnectorSyncJob", back_populates="external_source")


class ExternalItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_items"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "connection_id",
            "provider_item_id",
            name="uq_external_items_org_connection_provider_item",
        ),
        CheckConstraint(
            "item_type IN ('issue', 'wiki_page', 'cloud_file', 'folder', 'comment', 'attachment')",
            name="external_items_item_type_allowed",
        ),
        CheckConstraint(
            "visibility IN ('org_wide', 'collection', 'restricted')",
            name="external_items_visibility_allowed",
        ),
        CheckConstraint("length(trim(provider_item_id)) >= 1", name="external_items_id_not_blank"),
        CheckConstraint("length(trim(source_url)) >= 1", name="external_items_url_not_blank"),
        CheckConstraint("length(content_hash) = 64", name="external_items_content_hash_length"),
        CheckConstraint("sync_version >= 1", name="external_items_sync_version_positive"),
        Index("idx_external_items_org_type", "organization_id", "item_type"),
        Index("idx_external_items_source", "external_source_id"),
        Index("idx_external_items_collection_id", "collection_id"),
        Index("idx_external_items_parent", "organization_id", "provider_parent_id"),
        Index("idx_external_items_hash", "organization_id", "content_hash"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    connection_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_source_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("external_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_item_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider_parent_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    root_provider_item_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    item_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ExternalItemType.cloud_file.value,
    )
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sync_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ExternalItemVisibility.org_wide.value,
    )
    acl_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    permissions_json: Mapped[dict] = mapped_column(
        "permissions", JSON, nullable=False, default=dict
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization")
    connection = relationship("ConnectorConnection", back_populates="items")
    external_source = relationship("ExternalSource", back_populates="items")
    collection = relationship("Collection")
    source_documents = relationship(
        "SourceDocument",
        back_populates="external_item",
        cascade="all, delete-orphan",
    )
    source_references = relationship("SourceReference", back_populates="external_item")
