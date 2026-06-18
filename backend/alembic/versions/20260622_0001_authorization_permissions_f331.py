"""authorization permissions schema (F331)

Revision ID: 20260622_0001
Revises: 20260621_0002
Create Date: 2026-06-22

Adds the persistent authorization data model required for:
  - built-in role permissions
  - feature-level permissions
  - resource grants and denies with expirations
  - connector/source ACL mappings
  - authorization decision logging
  - authorization conflict tracking

The seed data is intentionally least-privilege for member/viewer roles and is
safe to re-apply during upgrades because the tables are created from scratch.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0001"
down_revision: str | None = "20260621_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

ACTION_VALUES = (
    "read_only",
    "manage",
    "sync",
    "export",
    "evaluate",
    "cite",
    "search",
)


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    ]


def _role_permission_rows() -> list[dict[str, object]]:
    seeds: dict[str, list[str]] = {
        "owner": [
            "documents:view",
            "documents:upload",
            "documents:delete",
            "documents:manage",
            "collections:view",
            "collections:create",
            "collections:manage",
            "collections:delete",
            "chat:use",
            "chat:use_collections",
            "chat:manage_sessions",
            "evaluations:view",
            "evaluations:create",
            "evaluations:run",
            "evaluations:manage",
            "audit_logs:view",
            "audit_logs:export",
            "security_center:view",
            "security_center:configure",
            "billing:view",
            "billing:manage",
            "api_keys:list",
            "api_keys:create",
            "api_keys:revoke",
            "webhooks:list",
            "webhooks:create",
            "webhooks:delete",
            "agents:use",
            "agents:create",
            "agents:manage",
            "mcp:use",
            "mcp:manage",
            "roles:view",
            "roles:manage",
            "team:view",
            "team:manage",
            "graph:view",
            "graph:entities:manage",
            "graph:relations:manage",
            "graph:governance:configure",
            "graph:audit_logs:view",
        ],
        "admin": [
            "documents:view",
            "documents:upload",
            "documents:delete",
            "documents:manage",
            "collections:view",
            "collections:create",
            "collections:manage",
            "collections:delete",
            "chat:use",
            "chat:use_collections",
            "chat:manage_sessions",
            "evaluations:view",
            "evaluations:create",
            "evaluations:run",
            "evaluations:manage",
            "audit_logs:view",
            "audit_logs:export",
            "security_center:view",
            "security_center:configure",
            "api_keys:list",
            "api_keys:create",
            "api_keys:revoke",
            "webhooks:list",
            "webhooks:create",
            "webhooks:delete",
            "agents:use",
            "agents:create",
            "agents:manage",
            "mcp:use",
            "mcp:manage",
            "roles:view",
            "roles:manage",
            "team:view",
            "team:manage",
            "graph:view",
            "graph:entities:manage",
            "graph:relations:manage",
            "graph:governance:configure",
            "graph:audit_logs:view",
        ],
        "member": [
            "documents:view",
            "documents:upload",
            "collections:view",
            "chat:use",
            "chat:use_collections",
            "chat:manage_sessions",
            "evaluations:view",
            "agents:use",
            "mcp:use",
            "graph:view",
        ],
        "viewer": [
            "documents:view",
            "collections:view",
            "chat:use",
            "evaluations:view",
            "agents:use",
            "mcp:use",
            "graph:view",
        ],
    }
    rows: list[dict[str, object]] = []
    for role_name, permissions in seeds.items():
        for permission_key in permissions:
            rows.append(
                {
                    "id": uuid5(NAMESPACE_URL, f"role-permission:{role_name}:{permission_key}"),
                    "role_name": role_name,
                    "permission_key": permission_key,
                    "is_enabled": True,
                    "source": "seed",
                }
            )
    return rows


def _feature_permission_rows() -> list[dict[str, object]]:
    all_actions = list(ACTION_VALUES)
    read_actions = ["read_only", "search", "cite"]
    read_only_actions = ["read_only", "search"]
    feature_rows: list[dict[str, object]] = []

    owner_features = {
        "documents": all_actions,
        "collections": all_actions,
        "chat": all_actions,
        "evaluations": all_actions,
        "citations": all_actions,
        "saved_answers": all_actions,
        "connectors": all_actions,
        "graph": all_actions,
        "agents": all_actions,
        "mcp": all_actions,
        "billing": all_actions,
        "security_center": all_actions,
        "api_keys": all_actions,
        "webhooks": all_actions,
        "roles": all_actions,
        "team": all_actions,
    }

    admin_features = {
        "documents": all_actions,
        "collections": all_actions,
        "chat": all_actions,
        "evaluations": all_actions,
        "citations": all_actions,
        "saved_answers": all_actions,
        "connectors": all_actions,
        "graph": all_actions,
        "agents": all_actions,
        "mcp": all_actions,
        "security_center": all_actions,
        "api_keys": all_actions,
        "webhooks": all_actions,
        "roles": all_actions,
        "team": all_actions,
    }

    member_features = {
        "documents": read_actions,
        "collections": read_actions,
        "chat": read_actions,
        "evaluations": read_only_actions,
        "citations": read_actions,
        "saved_answers": read_actions,
        "connectors": read_only_actions,
        "graph": read_actions,
        "agents": read_only_actions,
        "mcp": read_only_actions,
        "search": ["search"],
    }

    viewer_features = {
        "documents": read_actions,
        "collections": read_only_actions,
        "chat": read_only_actions,
        "evaluations": read_only_actions,
        "citations": read_actions,
        "saved_answers": read_actions,
        "connectors": read_only_actions,
        "graph": read_only_actions,
        "agents": read_only_actions,
        "mcp": read_only_actions,
        "search": ["search"],
    }

    role_feature_map = {
        "owner": owner_features,
        "admin": admin_features,
        "member": member_features,
        "viewer": viewer_features,
    }
    for role_name, features in role_feature_map.items():
        for feature_key, actions in features.items():
            for action in actions:
                feature_rows.append(
                    {
                        "id": uuid5(
                            NAMESPACE_URL,
                            f"feature-permission:{role_name}:{feature_key}:{action}",
                        ),
                        "role_name": role_name,
                        "feature_key": feature_key,
                        "action": action,
                        "is_enabled": True,
                        "source": "seed",
                    }
                )
    return feature_rows


def upgrade() -> None:
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role_name", sa.String(length=64), nullable=False),
        sa.Column("permission_key", sa.String(length=128), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_role_permissions_created_by_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_role_permissions"),
        sa.UniqueConstraint("role_name", "permission_key", name="uq_role_permissions_role_key"),
    )
    op.create_index("idx_role_permissions_role_name", "role_permissions", ["role_name"])
    op.create_index(
        "idx_role_permissions_permission_key",
        "role_permissions",
        ["permission_key"],
    )

    op.create_table(
        "feature_permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role_name", sa.String(length=64), nullable=False),
        sa.Column("feature_key", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_feature_permissions_created_by_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feature_permissions"),
        sa.UniqueConstraint(
            "role_name",
            "feature_key",
            "action",
            name="uq_feature_permissions_role_feature_action",
        ),
        sa.CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="feature_permissions_action_allowed",
        ),
    )
    op.create_index(
        "idx_feature_permissions_role_name",
        "feature_permissions",
        ["role_name"],
    )
    op.create_index(
        "idx_feature_permissions_feature_key",
        "feature_permissions",
        ["feature_key"],
    )
    op.create_index("idx_feature_permissions_action", "feature_permissions", ["action"])

    def _create_resource_access_table(table_name: str, pk_name: str) -> None:
        org_fk_name = f"{table_name}_org_id"
        user_fk_name = f"{table_name}_user_id"
        creator_fk_name = f"{table_name}_created_by_user_id"
        op.create_table(
            table_name,
            sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
            sa.Column("role_name", sa.String(length=64), nullable=True),
            sa.Column("principal_type", sa.String(length=32), nullable=False),
            sa.Column("principal_value", sa.String(length=255), nullable=False),
            sa.Column("resource_type", sa.String(length=128), nullable=False),
            sa.Column("resource_id", sa.String(length=255), nullable=True),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
            *_timestamp_columns(),
            sa.ForeignKeyConstraint(
                ["organization_id"],
                ["organizations.id"],
                name=org_fk_name,
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name=user_fk_name,
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name=creator_fk_name,
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name=pk_name),
            sa.CheckConstraint(
                "principal_type IN ('user', 'team', 'group', 'role')",
                name=f"{table_name}_principal_type_allowed",
            ),
            sa.CheckConstraint(
                "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
                name=f"{table_name}_action_allowed",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'scheduled', 'expired', 'revoked')",
                name=f"{table_name}_status_allowed",
            ),
        )
        op.create_index(
            f"idx_{table_name}_org_user",
            table_name,
            ["organization_id", "user_id"],
        )
        op.create_index(
            f"idx_{table_name}_org_principal",
            table_name,
            ["organization_id", "principal_type", "principal_value"],
        )
        op.create_index(
            f"idx_{table_name}_org_resource",
            table_name,
            ["organization_id", "resource_type", "resource_id"],
        )
        op.create_index(
            f"idx_{table_name}_org_action",
            table_name,
            ["organization_id", "action"],
        )
        op.create_index(
            f"idx_{table_name}_org_status",
            table_name,
            ["organization_id", "status"],
        )
        op.create_index(
            f"idx_{table_name}_expires_at",
            table_name,
            ["expires_at"],
        )

    _create_resource_access_table(
        "resource_access_grants",
        "pk_resource_access_grants",
    )
    _create_resource_access_table(
        "resource_access_denies",
        "pk_resource_access_denies",
    )

    op.create_table(
        "source_acl_mappings",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("connector_connection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_type", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("principal_type", sa.String(length=32), nullable=False),
        sa.Column("principal_value", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column(
            "acl_effect",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'allow'"),
        ),
        sa.Column("acl_hash", sa.String(length=64), nullable=True),
        sa.Column("is_inherited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_acl", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_source_acl_mappings_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_source_acl_mappings_user_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connector_connection_id"],
            ["connector_connections.id"],
            name="fk_source_acl_mappings_connector_connection_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_acl_mappings"),
        sa.CheckConstraint(
            "principal_type IN ('user', 'team', 'group', 'role')",
            name="source_acl_mappings_principal_type_allowed",
        ),
        sa.CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="source_acl_mappings_action_allowed",
        ),
        sa.CheckConstraint(
            "acl_effect IN ('allow', 'deny')",
            name="source_acl_mappings_acl_effect_allowed",
        ),
    )
    op.create_index(
        "idx_source_acl_mappings_org_source",
        "source_acl_mappings",
        ["organization_id", "source_type", "source_id"],
    )
    op.create_index(
        "idx_source_acl_mappings_org_connector",
        "source_acl_mappings",
        ["organization_id", "connector_connection_id"],
    )
    op.create_index(
        "idx_source_acl_mappings_org_user",
        "source_acl_mappings",
        ["organization_id", "user_id"],
    )
    op.create_index(
        "idx_source_acl_mappings_org_principal",
        "source_acl_mappings",
        ["organization_id", "principal_type", "principal_value"],
    )
    op.create_index(
        "idx_source_acl_mappings_acl_hash",
        "source_acl_mappings",
        ["organization_id", "acl_hash"],
    )

    op.create_table(
        "authorization_decision_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("role_name", sa.String(length=64), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_value", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("matched_rule", sa.String(length=128), nullable=True),
        sa.Column("deny_reason", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("policy_version", sa.String(length=64), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_authorization_decision_logs_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_authorization_decision_logs_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_authorization_decision_logs"),
        sa.CheckConstraint(
            "decision IN ('allow', 'deny')",
            name="authorization_decision_logs_decision_allowed",
        ),
        sa.CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="authorization_decision_logs_action_allowed",
        ),
    )
    op.create_index(
        "idx_authorization_decision_logs_org_created",
        "authorization_decision_logs",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "idx_authorization_decision_logs_org_user",
        "authorization_decision_logs",
        ["organization_id", "user_id"],
    )
    op.create_index(
        "idx_authorization_decision_logs_org_resource",
        "authorization_decision_logs",
        ["organization_id", "resource_type", "resource_id"],
    )
    op.create_index(
        "idx_authorization_decision_logs_org_action",
        "authorization_decision_logs",
        ["organization_id", "action"],
    )

    op.create_table(
        "authorization_conflicts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("role_name", sa.String(length=64), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_value", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("conflict_type", sa.String(length=64), nullable=False),
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'medium'"),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conflict_summary", sa.Text(), nullable=True),
        sa.Column("grant_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("deny_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("decision_log_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_authorization_conflicts_org_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_authorization_conflicts_user_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["resource_access_grants.id"],
            name="fk_authorization_conflicts_grant_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["deny_id"],
            ["resource_access_denies.id"],
            name="fk_authorization_conflicts_deny_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decision_log_id"],
            ["authorization_decision_logs.id"],
            name="fk_authorization_conflicts_decision_log_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_authorization_conflicts"),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'resolved', 'dismissed')",
            name="authorization_conflicts_status_allowed",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="authorization_conflicts_severity_allowed",
        ),
        sa.CheckConstraint(
            "action IN ('read_only', 'manage', 'sync', 'export', 'evaluate', 'cite', 'search')",
            name="authorization_conflicts_action_allowed",
        ),
    )
    op.create_index(
        "idx_authorization_conflicts_org_status",
        "authorization_conflicts",
        ["organization_id", "status"],
    )
    op.create_index(
        "idx_authorization_conflicts_org_resource",
        "authorization_conflicts",
        ["organization_id", "resource_type", "resource_id"],
    )
    op.create_index(
        "idx_authorization_conflicts_org_detected",
        "authorization_conflicts",
        ["organization_id", "detected_at"],
    )

    op.bulk_insert(
        sa.table(
            "role_permissions",
            sa.column("id", sa.Uuid()),
            sa.column("role_name", sa.String()),
            sa.column("permission_key", sa.String()),
            sa.column("is_enabled", sa.Boolean()),
            sa.column("source", sa.String()),
        ),
        _role_permission_rows(),
    )
    op.bulk_insert(
        sa.table(
            "feature_permissions",
            sa.column("id", sa.Uuid()),
            sa.column("role_name", sa.String()),
            sa.column("feature_key", sa.String()),
            sa.column("action", sa.String()),
            sa.column("is_enabled", sa.Boolean()),
            sa.column("source", sa.String()),
        ),
        _feature_permission_rows(),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_authorization_conflicts_org_detected",
        table_name="authorization_conflicts",
    )
    op.drop_index(
        "idx_authorization_conflicts_org_resource",
        table_name="authorization_conflicts",
    )
    op.drop_index(
        "idx_authorization_conflicts_org_status",
        table_name="authorization_conflicts",
    )
    op.drop_table("authorization_conflicts")

    op.drop_index(
        "idx_authorization_decision_logs_org_action",
        table_name="authorization_decision_logs",
    )
    op.drop_index(
        "idx_authorization_decision_logs_org_resource",
        table_name="authorization_decision_logs",
    )
    op.drop_index(
        "idx_authorization_decision_logs_org_user",
        table_name="authorization_decision_logs",
    )
    op.drop_index(
        "idx_authorization_decision_logs_org_created",
        table_name="authorization_decision_logs",
    )
    op.drop_table("authorization_decision_logs")

    op.drop_index(
        "idx_source_acl_mappings_acl_hash",
        table_name="source_acl_mappings",
    )
    op.drop_index(
        "idx_source_acl_mappings_org_principal",
        table_name="source_acl_mappings",
    )
    op.drop_index(
        "idx_source_acl_mappings_org_user",
        table_name="source_acl_mappings",
    )
    op.drop_index(
        "idx_source_acl_mappings_org_source",
        table_name="source_acl_mappings",
    )
    op.drop_index(
        "idx_source_acl_mappings_org_connector",
        table_name="source_acl_mappings",
    )
    op.drop_table("source_acl_mappings")

    for table_name in ("resource_access_denies", "resource_access_grants"):
        op.drop_index(
            f"idx_{table_name}_expires_at",
            table_name=table_name,
        )
        op.drop_index(
            f"idx_{table_name}_org_status",
            table_name=table_name,
        )
        op.drop_index(
            f"idx_{table_name}_org_action",
            table_name=table_name,
        )
        op.drop_index(
            f"idx_{table_name}_org_resource",
            table_name=table_name,
        )
        op.drop_index(
            f"idx_{table_name}_org_principal",
            table_name=table_name,
        )
        op.drop_index(
            f"idx_{table_name}_org_user",
            table_name=table_name,
        )
        op.drop_table(table_name)

    op.drop_index("idx_feature_permissions_action", table_name="feature_permissions")
    op.drop_index(
        "idx_feature_permissions_feature_key",
        table_name="feature_permissions",
    )
    op.drop_index("idx_feature_permissions_role_name", table_name="feature_permissions")
    op.drop_table("feature_permissions")

    op.drop_index("idx_role_permissions_permission_key", table_name="role_permissions")
    op.drop_index("idx_role_permissions_role_name", table_name="role_permissions")
    op.drop_table("role_permissions")
