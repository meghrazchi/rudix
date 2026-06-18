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
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

AUTHORIZATION_ACTIONS = (
    "read_only",
    "manage",
    "sync",
    "export",
    "evaluate",
    "cite",
    "search",
)

PRINCIPAL_TYPES = ("user", "team", "group", "role")

GRANT_STATUSES = ("active", "scheduled", "expired", "revoked")

CONFLICT_STATUSES = ("open", "investigating", "resolved", "dismissed")

DECISION_RESULTS = ("allow", "deny")


class RolePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_name", "permission_key", name="uq_role_permissions_role_key"),
        Index("idx_role_permissions_role_name", "role_name"),
        Index("idx_role_permissions_permission_key", "permission_key"),
    )

    role_name: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_key: Mapped[str] = mapped_column(String(128), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by = relationship("User", foreign_keys=[created_by_user_id])


class FeaturePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feature_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role_name",
            "feature_key",
            "action",
            name="uq_feature_permissions_role_feature_action",
        ),
        CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="feature_permissions_action_allowed",
        ),
        Index("idx_feature_permissions_role_name", "role_name"),
        Index("idx_feature_permissions_feature_key", "feature_key"),
        Index("idx_feature_permissions_action", "action"),
    )

    role_name: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_key: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by = relationship("User", foreign_keys=[created_by_user_id])


class _ResourceAccessBase(UUIDPrimaryKeyMixin, TimestampMixin):
    __abstract__ = True

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    role_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_value: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class ResourceAccessGrant(_ResourceAccessBase, Base):
    __tablename__ = "resource_access_grants"
    __table_args__ = (
        CheckConstraint(
            "principal_type IN ('user', 'team', 'group', 'role')",
            name="resource_access_grants_principal_type_allowed",
        ),
        CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="resource_access_grants_action_allowed",
        ),
        CheckConstraint(
            "status IN ('active', 'scheduled', 'expired', 'revoked')",
            name="resource_access_grants_status_allowed",
        ),
        Index("idx_resource_access_grants_org_user", "organization_id", "user_id"),
        Index(
            "idx_resource_access_grants_org_principal",
            "organization_id",
            "principal_type",
            "principal_value",
        ),
        Index(
            "idx_resource_access_grants_org_resource",
            "organization_id",
            "resource_type",
            "resource_id",
        ),
        Index("idx_resource_access_grants_org_action", "organization_id", "action"),
        Index("idx_resource_access_grants_org_status", "organization_id", "status"),
        Index("idx_resource_access_grants_expires_at", "expires_at"),
    )


class ResourceAccessDeny(_ResourceAccessBase, Base):
    __tablename__ = "resource_access_denies"
    __table_args__ = (
        CheckConstraint(
            "principal_type IN ('user', 'team', 'group', 'role')",
            name="resource_access_denies_principal_type_allowed",
        ),
        CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="resource_access_denies_action_allowed",
        ),
        CheckConstraint(
            "status IN ('active', 'scheduled', 'expired', 'revoked')",
            name="resource_access_denies_status_allowed",
        ),
        Index("idx_resource_access_denies_org_user", "organization_id", "user_id"),
        Index(
            "idx_resource_access_denies_org_principal",
            "organization_id",
            "principal_type",
            "principal_value",
        ),
        Index(
            "idx_resource_access_denies_org_resource",
            "organization_id",
            "resource_type",
            "resource_id",
        ),
        Index("idx_resource_access_denies_org_action", "organization_id", "action"),
        Index("idx_resource_access_denies_org_status", "organization_id", "status"),
        Index("idx_resource_access_denies_expires_at", "expires_at"),
    )


class SourceAclMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_acl_mappings"
    __table_args__ = (
        CheckConstraint(
            "principal_type IN ('user', 'team', 'group', 'role')",
            name="source_acl_mappings_principal_type_allowed",
        ),
        CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="source_acl_mappings_action_allowed",
        ),
        Index("idx_source_acl_mappings_org_source", "organization_id", "source_type", "source_id"),
        Index(
            "idx_source_acl_mappings_org_connector",
            "organization_id",
            "connector_connection_id",
        ),
        Index("idx_source_acl_mappings_org_user", "organization_id", "user_id"),
        Index(
            "idx_source_acl_mappings_org_principal",
            "organization_id",
            "principal_type",
            "principal_value",
        ),
        Index("idx_source_acl_mappings_acl_hash", "organization_id", "acl_hash"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    connector_connection_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_value: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    acl_effect: Mapped[str] = mapped_column(String(16), nullable=False, default="allow")
    acl_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_inherited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_acl_json: Mapped[dict] = mapped_column("raw_acl", JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    subject_user = relationship("User", foreign_keys=[user_id])


class AuthorizationDecisionLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "authorization_decision_logs"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('allow', 'deny')",
            name="authorization_decision_logs_decision_allowed",
        ),
        CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="authorization_decision_logs_action_allowed",
        ),
        Index("idx_authorization_decision_logs_org_created", "organization_id", "created_at"),
        Index("idx_authorization_decision_logs_org_user", "organization_id", "user_id"),
        Index(
            "idx_authorization_decision_logs_org_resource",
            "organization_id",
            "resource_type",
            "resource_id",
        ),
        Index("idx_authorization_decision_logs_org_action", "organization_id", "action"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    role_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_value: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    matched_rule: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deny_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_json: Mapped[list] = mapped_column("trace", JSON, nullable=False, default=list)
    context_json: Mapped[dict] = mapped_column("context", JSON, nullable=False, default=dict)

    subject_user = relationship("User", foreign_keys=[user_id])


class AuthorizationConflict(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "authorization_conflicts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'investigating', 'resolved', 'dismissed')",
            name="authorization_conflicts_status_allowed",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="authorization_conflicts_severity_allowed",
        ),
        CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="authorization_conflicts_action_allowed",
        ),
        Index("idx_authorization_conflicts_org_status", "organization_id", "status"),
        Index(
            "idx_authorization_conflicts_org_resource",
            "organization_id",
            "resource_type",
            "resource_id",
        ),
        Index("idx_authorization_conflicts_org_detected", "organization_id", "detected_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    role_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_value: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conflict_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    grant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    deny_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    decision_log_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    conflict_context_json: Mapped[dict] = mapped_column(
        "context", JSON, nullable=False, default=dict
    )

    subject_user = relationship("User", foreign_keys=[user_id])
