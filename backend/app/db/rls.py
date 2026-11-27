"""PostgreSQL Row-Level Security (RLS) policy definitions for multi-tenant tables."""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

TENANT_RLS_POLICY_NAME = "tenant_isolation_policy"

TENANT_RLS_TABLES: tuple[str, ...] = (
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


def _validate_identifier(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return identifier


def build_enable_rls_sql(table_name: str) -> tuple[str, str, str]:
    """Return DDL statements to enable PostgreSQL RLS and create tenant policy on `table_name`."""
    safe_table = _validate_identifier(table_name)
    condition = (
        "NULLIF(current_setting('app.current_organization_id', true), '') IS NULL "
        "OR organization_id = "
        "NULLIF(current_setting('app.current_organization_id', true), '')::uuid"
    )
    enable_sql = f"ALTER TABLE {safe_table} ENABLE ROW LEVEL SECURITY"
    drop_existing_sql = f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON {safe_table}"
    create_policy_sql = (
        f"CREATE POLICY {TENANT_RLS_POLICY_NAME} ON {safe_table} "
        f"USING ({condition}) WITH CHECK ({condition})"
    )
    return enable_sql, drop_existing_sql, create_policy_sql


def build_disable_rls_sql(table_name: str) -> tuple[str, str]:
    """Return DDL statements to drop the tenant policy and disable PostgreSQL RLS on `table_name`."""
    safe_table = _validate_identifier(table_name)
    drop_policy_sql = f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON {safe_table}"
    disable_sql = f"ALTER TABLE {safe_table} DISABLE ROW LEVEL SECURITY"
    return drop_policy_sql, disable_sql


# --- R04-08: mode-aware policies -------------------------------------------------------
# The legacy names above stay frozen because migration 20260715_0001 imports them at run
# time. Migration 20261127_0004 copies the lists below as literals; keep them in sync
# (tests/test_rls_coverage.py checks both directions).

_SETTING_ORG = "NULLIF(current_setting('app.current_organization_id', true), '')"
_SETTING_MODE = "COALESCE(current_setting('app.rls_mode', true), '')"

# Tables read before a tenant is known (credential, token and share lookups, SSO and SCIM
# discovery, OAuth state, bot inbound events, the public status page). Their policy keeps
# the legacy condition: an unset tenant sees all rows, a bound tenant sees only its own.
RLS_LOOKUP_TABLES: tuple[str, ...] = (
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

# User-scoped identity tables. One user spans several organizations (home organization on
# ``users``, one ``organization_members`` row and refresh sessions per organization), and a
# request bound to organization B must still read the user, list every membership for the
# workspace switcher, and revoke the user's sessions in every organization (logout-all,
# password change). A tenant policy would hide those rows, so these tables get no policy
# and keep RLS disabled, as before; the ORM guard exempts ``User`` and
# ``OrganizationMember`` for the same reason.
RLS_IDENTITY_TABLES: tuple[str, ...] = (
    "users",
    "organization_members",
    "auth_refresh_sessions",
)

# Every other table with an ``organization_id`` column. In ``strict`` mode an unset tenant
# sees no rows and cannot write.
RLS_STRICT_TABLES: tuple[str, ...] = (
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

LEGACY_RLS_CONDITION = f"{_SETTING_ORG} IS NULL OR organization_id = {_SETTING_ORG}::uuid"
STRICT_RLS_CONDITION = (
    f"organization_id = {_SETTING_ORG}::uuid "
    f"OR ({_SETTING_ORG} IS NULL AND {_SETTING_MODE} <> 'strict')"
)


def _build_policy_sql(table_name: str, condition: str) -> tuple[str, str, str]:
    safe_table = _validate_identifier(table_name)
    return (
        f"ALTER TABLE {safe_table} ENABLE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {TENANT_RLS_POLICY_NAME} ON {safe_table}",
        (
            f"CREATE POLICY {TENANT_RLS_POLICY_NAME} ON {safe_table} "
            f"USING ({condition}) WITH CHECK ({condition})"
        ),
    )


def build_strict_policy_sql(table_name: str) -> tuple[str, str, str]:
    """DDL for a policy that denies an unset tenant when ``app.rls_mode = 'strict'``."""
    return _build_policy_sql(table_name, STRICT_RLS_CONDITION)


def build_lookup_policy_sql(table_name: str) -> tuple[str, str, str]:
    """DDL for a pre-auth lookup table: an unset tenant is never denied."""
    return _build_policy_sql(table_name, LEGACY_RLS_CONDITION)
