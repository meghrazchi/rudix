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
    "saved_answers",
    "knowledge_cards",
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
