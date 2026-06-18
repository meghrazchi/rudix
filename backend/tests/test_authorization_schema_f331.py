from importlib import util
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260622_0001_authorization_permissions_f331.py"
)


def _load_migration():
    spec = util.spec_from_file_location("migration_20260622_0001", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load authorization migration module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_reference_tables(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "organizations",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
    )
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
    )
    sa.Table(
        "connector_connections",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
    )
    metadata.create_all(connection)


def test_authorization_migration_upgrade_downgrade_smoke() -> None:
    migration_module = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_reference_tables(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration_module.upgrade()

            inspector = sa.inspect(connection)
            table_names = set(inspector.get_table_names())
            assert {
                "role_permissions",
                "feature_permissions",
                "resource_access_grants",
                "resource_access_denies",
                "source_acl_mappings",
                "authorization_decision_logs",
                "authorization_conflicts",
            }.issubset(table_names)

            role_indexes = {index["name"] for index in inspector.get_indexes("role_permissions")}
            assert "idx_role_permissions_role_name" in role_indexes
            assert "idx_role_permissions_permission_key" in role_indexes

            grant_indexes = {
                index["name"] for index in inspector.get_indexes("resource_access_grants")
            }
            assert "idx_resource_access_grants_org_user" in grant_indexes
            assert "idx_resource_access_grants_org_status" in grant_indexes
            assert "idx_resource_access_grants_expires_at" in grant_indexes

            decision_indexes = {
                index["name"] for index in inspector.get_indexes("authorization_decision_logs")
            }
            assert "idx_authorization_decision_logs_org_created" in decision_indexes
            assert "idx_authorization_decision_logs_org_resource" in decision_indexes

            migration_module.downgrade()
            remaining_tables = set(sa.inspect(connection).get_table_names())
            assert remaining_tables == {"organizations", "users", "connector_connections"}


def test_authorization_seed_rows_are_least_privilege() -> None:
    migration_module = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_reference_tables(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration_module.upgrade()

            viewer_permissions = {
                row[0]
                for row in connection.execute(
                    sa.text("SELECT permission_key FROM role_permissions WHERE role_name = :role"),
                    {"role": "viewer"},
                )
            }
            assert "documents:view" in viewer_permissions
            assert "billing:manage" not in viewer_permissions

            member_feature_actions = {
                (row[0], row[1])
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT feature_key, action
                        FROM feature_permissions
                        WHERE role_name = :role AND is_enabled = 1
                        """
                    ),
                    {"role": "member"},
                )
            }
            assert ("documents", "read_only") in member_feature_actions
            assert ("documents", "manage") not in member_feature_actions
            assert ("billing", "read_only") not in member_feature_actions

            owner_feature_actions = {
                (row[0], row[1])
                for row in connection.execute(
                    sa.text(
                        """
                        SELECT feature_key, action
                        FROM feature_permissions
                        WHERE role_name = :role AND is_enabled = 1
                        """
                    ),
                    {"role": "owner"},
                )
            }
            assert ("billing", "manage") in owner_feature_actions
            assert ("team", "search") in owner_feature_actions


def test_authorization_grant_deny_and_conflict_rows() -> None:
    migration_module = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_reference_tables(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration_module.upgrade()

            org_id = str(uuid4())
            user_id = str(uuid4())
            connection.execute(
                sa.text("INSERT INTO organizations (id) VALUES (:id)"),
                {"id": org_id},
            )
            connection.execute(
                sa.text("INSERT INTO users (id) VALUES (:id)"),
                {"id": user_id},
            )
            connector_connection_id = str(uuid4())
            connection.execute(
                sa.text("INSERT INTO connector_connections (id) VALUES (:id)"),
                {"id": connector_connection_id},
            )

            grant_id = str(uuid4())
            deny_id = str(uuid4())
            decision_log_id = str(uuid4())

            connection.execute(
                sa.text(
                    """
                    INSERT INTO resource_access_grants (
                        id, organization_id, user_id, principal_type, principal_value,
                        resource_type, resource_id, action, status, reason
                    ) VALUES (
                        :id, :organization_id, :user_id, :principal_type, :principal_value,
                        :resource_type, :resource_id, :action, :status, :reason
                    )
                    """
                ),
                {
                    "id": grant_id,
                    "organization_id": org_id,
                    "user_id": user_id,
                    "principal_type": "user",
                    "principal_value": str(user_id),
                    "resource_type": "document",
                    "resource_id": "doc-1",
                    "action": "read_only",
                    "status": "active",
                    "reason": "temporary review access",
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO resource_access_denies (
                        id, organization_id, user_id, principal_type, principal_value,
                        resource_type, resource_id, action, status, reason
                    ) VALUES (
                        :id, :organization_id, :user_id, :principal_type, :principal_value,
                        :resource_type, :resource_id, :action, :status, :reason
                    )
                    """
                ),
                {
                    "id": deny_id,
                    "organization_id": org_id,
                    "user_id": user_id,
                    "principal_type": "user",
                    "principal_value": str(user_id),
                    "resource_type": "document",
                    "resource_id": "doc-1",
                    "action": "manage",
                    "status": "active",
                    "reason": "explicit block",
                },
            )

            connection.execute(
                sa.text(
                    """
                    INSERT INTO authorization_decision_logs (
                        id, organization_id, user_id, subject_type, subject_value,
                        resource_type, resource_id, action, decision, matched_rule,
                        request_id, policy_version
                    ) VALUES (
                        :id, :organization_id, :user_id, :subject_type, :subject_value,
                        :resource_type, :resource_id, :action, :decision, :matched_rule,
                        :request_id, :policy_version
                    )
                    """
                ),
                {
                    "id": decision_log_id,
                    "organization_id": org_id,
                    "user_id": user_id,
                    "subject_type": "user",
                    "subject_value": str(user_id),
                    "resource_type": "document",
                    "resource_id": "doc-1",
                    "action": "manage",
                    "decision": "deny",
                    "matched_rule": "explicit_resource_deny",
                    "request_id": "req-123",
                    "policy_version": "f331",
                },
            )

            conflict_id = str(uuid4())
            connection.execute(
                sa.text(
                    """
                    INSERT INTO authorization_conflicts (
                        id, organization_id, user_id, subject_type, subject_value,
                        resource_type, resource_id, action, conflict_type, severity,
                        status, detected_at, grant_id, deny_id, decision_log_id,
                        conflict_summary
                    ) VALUES (
                        :id, :organization_id, :user_id, :subject_type, :subject_value,
                        :resource_type, :resource_id, :action, :conflict_type, :severity,
                        :status, CURRENT_TIMESTAMP, :grant_id, :deny_id, :decision_log_id,
                        :conflict_summary
                    )
                    """
                ),
                {
                    "id": conflict_id,
                    "organization_id": org_id,
                    "user_id": user_id,
                    "subject_type": "user",
                    "subject_value": str(user_id),
                    "resource_type": "document",
                    "resource_id": "doc-1",
                    "action": "manage",
                    "conflict_type": "grant_vs_deny",
                    "severity": "high",
                    "status": "open",
                    "grant_id": grant_id,
                    "deny_id": deny_id,
                    "decision_log_id": decision_log_id,
                    "conflict_summary": "User has both an allow and a deny for the same document action.",
                },
            )

            connection.execute(
                sa.text(
                    """
                    INSERT INTO source_acl_mappings (
                        id, organization_id, connector_connection_id, source_type,
                        source_id, user_id, principal_type, principal_value,
                        action, acl_effect, acl_hash, is_inherited, is_active
                    ) VALUES (
                        :id, :organization_id, :connector_connection_id, :source_type,
                        :source_id, :user_id, :principal_type, :principal_value,
                        :action, :acl_effect, :acl_hash, :is_inherited, :is_active
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "organization_id": org_id,
                    "connector_connection_id": connector_connection_id,
                    "source_type": "connector_item",
                    "source_id": "item-1",
                    "user_id": user_id,
                    "principal_type": "team",
                    "principal_value": "eng",
                    "action": "read_only",
                    "acl_effect": "allow",
                    "acl_hash": "a" * 64,
                    "is_inherited": False,
                    "is_active": True,
                },
            )

            grant_count = connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM resource_access_grants WHERE organization_id = :organization_id"
                ),
                {"organization_id": org_id},
            ).scalar_one()
            deny_count = connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM resource_access_denies WHERE organization_id = :organization_id"
                ),
                {"organization_id": org_id},
            ).scalar_one()
            conflict_count = connection.execute(
                sa.text(
                    "SELECT COUNT(*) FROM authorization_conflicts WHERE organization_id = :organization_id"
                ),
                {"organization_id": org_id},
            ).scalar_one()

            assert grant_count == 1
            assert deny_count == 1
            assert conflict_count == 1

            conflict_row = connection.execute(
                sa.text(
                    """
                    SELECT conflict_type, severity, status, grant_id, deny_id, decision_log_id
                    FROM authorization_conflicts
                    WHERE id = :id
                    """
                ),
                {"id": conflict_id},
            ).one()
            assert conflict_row.conflict_type == "grant_vs_deny"
            assert conflict_row.severity == "high"
            assert conflict_row.status == "open"
