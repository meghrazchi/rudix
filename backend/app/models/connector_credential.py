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
from app.models.enums import ConnectorAuthType, ConnectorCredentialStatus


class ConnectorCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_credentials"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "version",
            name="uq_connector_credentials_connection_version",
        ),
        CheckConstraint(
            "auth_type IN ('oauth2', 'api_token', 'service_account', 'basic')",
            name="connector_credentials_auth_type_allowed",
        ),
        CheckConstraint(
            "status IN ('active', 'expired', 'revoked', 'error')",
            name="connector_credentials_status_allowed",
        ),
        CheckConstraint("version >= 1", name="connector_credentials_version_positive"),
        CheckConstraint(
            "length(trim(encryption_key_id)) >= 1",
            name="connector_credentials_key_id_not_blank",
        ),
        CheckConstraint(
            "length(trim(encryption_algorithm)) >= 1",
            name="connector_credentials_algorithm_not_blank",
        ),
        CheckConstraint(
            "length(secret_fingerprint) = 64",
            name="connector_credentials_fingerprint_length",
        ),
        Index("idx_connector_credentials_org_connection", "organization_id", "connection_id"),
        Index("idx_connector_credentials_current", "connection_id", "is_current"),
        Index("idx_connector_credentials_status_expires", "status", "expires_at"),
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
    auth_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectorAuthType.oauth2.value,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectorCredentialStatus.active.value,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    encryption_algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes_json: Mapped[list] = mapped_column("scopes", JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization = relationship("Organization")
    connection = relationship("ConnectorConnection", back_populates="credentials")


class ConnectorOAuthState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_oauth_states"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_connector_oauth_states_state_hash"),
        CheckConstraint(
            "length(state_hash) = 64",
            name="connector_oauth_states_state_hash_length",
        ),
        CheckConstraint(
            "connection_id IS NULL OR organization_id IS NOT NULL",
            name="connector_oauth_states_connection_has_org",
        ),
        Index("idx_connector_oauth_states_org_provider", "organization_id", "provider_key"),
        Index("idx_connector_oauth_states_connection", "connection_id"),
        Index("idx_connector_oauth_states_expires", "expires_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    connection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=True,
    )
    collection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_account_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    requested_scopes_json: Mapped[list] = mapped_column(
        "requested_scopes", JSON, nullable=False, default=list
    )
    config_json: Mapped[dict] = mapped_column("config", JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    organization = relationship("Organization")
    connection = relationship("ConnectorConnection")
    collection = relationship("Collection")
    created_by_user = relationship("User")
