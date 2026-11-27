"""mode-aware tenant row-level security policies (R04-08)

Revision ID: 20261127_0004
Revises: 20261127_0003
Create Date: 2026-11-27 00:00:00.000000

Extends PostgreSQL row-level security from the 12 tables of 20260715_0001 to every table
with an ``organization_id`` column and makes the policy aware of ``app.rls_mode``:

- Strict tables: a bound tenant (``app.current_organization_id``) sees and writes only its
  own rows. An unset tenant sees every row unless ``app.rls_mode = 'strict'``, in which
  case it sees none and cannot write.
- Lookup tables (read before a tenant is known: credentials, share tokens, SSO and SCIM
  discovery, OAuth state, bot inbound, public status): the legacy condition, an unset
  tenant is never denied.

Data-safety notes:
- No rows or columns change. ``FORCE ROW LEVEL SECURITY`` is not applied, so the table
  owner (the role migrations run as, and today's application role) is not affected. The
  policy only constrains a non-owner role without ``BYPASSRLS`` (``deploy/sql``), and only
  denies rows when the application sets ``app.rls_mode = 'strict'``. With no setting the
  behaviour equals the legacy policy.
- Locks: ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` and ``CREATE/DROP POLICY`` take a
  brief ACCESS EXCLUSIVE lock per table. ``lock_timeout = '5s'`` makes the migration fail
  instead of queueing behind a long transaction (and blocking traffic behind it); rerun it
  at low traffic. The DDL is metadata only and does not rewrite tables.
- The table lists are literals on purpose: later edits of ``app.db.rls`` must not change
  what this revision did. Tables that do not exist are skipped.
- Rollback: downgrade drops the policy and disables RLS on the tables outside the legacy 12
  and restores the legacy policy on the legacy 12 (state of 20260715_0001).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261127_0004"
down_revision: str | None = "20261127_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

POLICY_NAME = "tenant_isolation_policy"

LEGACY_TABLES: tuple[str, ...] = (
    "documents",
    "collections",
    "chat_sessions",
    "connector_connections",
    "external_items",
    "api_keys",
    "service_accounts",
    "audit_logs",
    "usage_events",
    "verified_answers",
    "answer_shares",
    "report_events",
)

LOOKUP_TABLES: tuple[str, ...] = (
    "users",
    "organization_members",
    "auth_refresh_sessions",
    "api_keys",
    "service_accounts",
    "service_account_tokens",
    "organization_invitations",
    "chat_shares",
    "answer_shares",
    "agent_trace_share_tokens",
    "org_sso_configs",
    "org_domain_verifications",
    "org_scim_configs",
    "bot_installations",
    "bot_user_mappings",
    "connector_oauth_states",
    "incidents",
    "incident_notes",
)

STRICT_TABLES: tuple[str, ...] = (
    "ab_experiments",
    "activity_timeline_events",
    "agent_approvals",
    "agent_runs",
    "agent_steps",
    "agent_tool_calls",
    "agent_tool_policy_overrides",
    "agent_trace_retention_policies",
    "audit_logs",
    "authorization_conflicts",
    "authorization_decision_logs",
    "chat_sessions",
    "collections",
    "connector_connections",
    "connector_credentials",
    "connector_permission_reviews",
    "connector_sync_conflicts",
    "connector_sync_jobs",
    "connector_sync_runs",
    "custom_roles",
    "document_metadata",
    "document_versions",
    "documents",
    "email_delivery_logs",
    "evaluation_sets",
    "external_item_tombstones",
    "external_items",
    "external_sources",
    "failed_job_audit_logs",
    "failed_jobs",
    "feedback_review_items",
    "message_feedback",
    "metadata_audit_log",
    "metadata_fields",
    "notifications",
    "org_ai_response_policies",
    "org_feature_flag_overrides",
    "org_freshness_policies",
    "org_mcp_policies",
    "org_model_profile_change_log",
    "org_model_profiles",
    "org_model_provider_change_log",
    "org_model_provider_settings",
    "org_quota_change_log",
    "org_quota_override",
    "org_quota_policy",
    "org_quota_usage",
    "org_workflows",
    "organization_chunking_profiles",
    "organization_governance_policies",
    "pipeline_runs",
    "policy_evaluation_logs",
    "prompt_templates",
    "quality_gates",
    "query_knowledge_gaps",
    "rag_profile_collection_overrides",
    "rag_profiles",
    "report_events",
    "resource_access_denies",
    "resource_access_grants",
    "safety_eval_cases",
    "safety_eval_runs",
    "source_acl_mappings",
    "source_documents",
    "source_references",
    "usage_events",
    "user_memory_preferences",
    "user_notification_preferences",
    "verified_answers",
    "webhook_deliveries",
    "webhooks",
    "workspace_portability_jobs",
)

_ORG = "NULLIF(current_setting('app.current_organization_id', true), '')"
_MODE = "COALESCE(current_setting('app.rls_mode', true), '')"
LEGACY_CONDITION = f"{_ORG} IS NULL OR organization_id = {_ORG}::uuid"
STRICT_CONDITION = f"organization_id = {_ORG}::uuid OR ({_ORG} IS NULL AND {_MODE} <> 'strict')"


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_policy(table: str, condition: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table}")
    op.execute(
        f"CREATE POLICY {POLICY_NAME} ON {table} USING ({condition}) WITH CHECK ({condition})"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    existing = _existing_tables()
    op.execute("SET lock_timeout = '5s'")
    for table in STRICT_TABLES:
        if table in existing:
            _create_policy(table, STRICT_CONDITION)
    for table in LOOKUP_TABLES:
        if table in existing:
            _create_policy(table, LEGACY_CONDITION)
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    existing = _existing_tables()
    op.execute("SET lock_timeout = '5s'")
    for table in (*STRICT_TABLES, *LOOKUP_TABLES):
        if table not in existing:
            continue
        if table in LEGACY_TABLES:
            _create_policy(table, LEGACY_CONDITION)
        else:
            op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("RESET lock_timeout")
