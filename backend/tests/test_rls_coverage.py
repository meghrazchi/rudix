"""Every tenant table is covered by exactly one RLS policy list (R04-08)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.db import rls, tenant_context
from app.db.base import Base

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "20261127_0004_tenant_rls_modes.py"
)
MIGRATION_0_6_0_PATH = MIGRATION_PATH.with_name("20261128_0001_document_processing_stages.py")


def _load_migration(path: Path = MIGRATION_PATH) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tenant_tables() -> set[str]:
    return {table.name for table in Base.metadata.tables.values() if "organization_id" in table.c}


def test_every_organization_table_is_in_exactly_one_list() -> None:
    strict = set(rls.RLS_STRICT_TABLES)
    lookup = set(rls.RLS_LOOKUP_TABLES)
    identity = set(rls.RLS_IDENTITY_TABLES)
    assert len(strict) == len(rls.RLS_STRICT_TABLES), "duplicate in RLS_STRICT_TABLES"
    assert len(lookup) == len(rls.RLS_LOOKUP_TABLES), "duplicate in RLS_LOOKUP_TABLES"
    assert len(identity) == len(rls.RLS_IDENTITY_TABLES), "duplicate in RLS_IDENTITY_TABLES"
    assert not strict & lookup
    assert not identity & (strict | lookup)
    tables = _tenant_tables()
    covered = strict | lookup | identity
    assert sorted(tables - covered) == [], "add new tenant tables to app.db.rls"
    assert sorted(covered - tables) == [], "stale table in app.db.rls"


def test_orm_guard_exempt_models_have_no_tenant_policy() -> None:
    # Models the ORM guard exempts as cross-organization identity lookups must not get a
    # database policy that filters them by the bound tenant either.
    exempt_tables = {
        mapper.local_table.name
        for mapper in Base.registry.mappers
        if mapper.class_.__name__ in tenant_context._EXEMPT_MODEL_NAMES
        and "organization_id" in mapper.local_table.c
    }
    assert exempt_tables == {"users", "organization_members"}
    assert exempt_tables <= set(rls.RLS_IDENTITY_TABLES)
    assert not set(rls.RLS_IDENTITY_TABLES) & set(rls.TENANT_RLS_TABLES)


def test_legacy_tables_are_all_covered() -> None:
    covered = set(rls.RLS_STRICT_TABLES) | set(rls.RLS_LOOKUP_TABLES)
    assert set(rls.TENANT_RLS_TABLES) <= covered


def test_migration_literal_lists_match_constants() -> None:
    migration = _load_migration()
    assert migration.revision == "20261127_0004"
    assert migration.down_revision == "20261127_0003"
    assert tuple(migration.STRICT_TABLES) == rls.RLS_STRICT_TABLES_0_4_0
    assert tuple(migration.LOOKUP_TABLES) == rls.RLS_LOOKUP_TABLES
    assert tuple(migration.IDENTITY_TABLES) == rls.RLS_IDENTITY_TABLES
    assert tuple(migration.LEGACY_TABLES) == rls.TENANT_RLS_TABLES
    assert migration.STRICT_CONDITION == rls.STRICT_RLS_CONDITION
    assert migration.LEGACY_CONDITION == rls.LEGACY_RLS_CONDITION


def test_0_6_0_migration_literal_matches_the_prefix_it_created() -> None:
    migration = _load_migration(MIGRATION_0_6_0_PATH)
    assert migration.revision == "20261128_0001"
    created = tuple(migration.STRICT_TABLES)
    assert created == rls.RLS_STRICT_TABLES_0_6_0[: len(created)]
    assert rls.RLS_STRICT_TABLES == rls.RLS_STRICT_TABLES_0_4_0 + rls.RLS_STRICT_TABLES_0_6_0


def test_legacy_builder_is_unchanged() -> None:
    # Migration 20260715_0001 imports this builder at run time; its output must not change.
    enable_sql, drop_sql, create_sql = rls.build_enable_rls_sql("documents")
    assert enable_sql == "ALTER TABLE documents ENABLE ROW LEVEL SECURITY"
    assert drop_sql == "DROP POLICY IF EXISTS tenant_isolation_policy ON documents"
    assert create_sql == (
        "CREATE POLICY tenant_isolation_policy ON documents USING ("
        "NULLIF(current_setting('app.current_organization_id', true), '') IS NULL "
        "OR organization_id = "
        "NULLIF(current_setting('app.current_organization_id', true), '')::uuid"
        ") WITH CHECK ("
        "NULLIF(current_setting('app.current_organization_id', true), '') IS NULL "
        "OR organization_id = "
        "NULLIF(current_setting('app.current_organization_id', true), '')::uuid)"
    )
    assert rls.build_lookup_policy_sql("documents")[2] == create_sql


def test_strict_builder_uses_mode_condition() -> None:
    _, _, create_sql = rls.build_strict_policy_sql("chat_sessions")
    assert create_sql.startswith("CREATE POLICY tenant_isolation_policy ON chat_sessions USING (")
    assert "app.rls_mode" in create_sql
    assert create_sql.count(rls.STRICT_RLS_CONDITION) == 2


def test_builders_reject_unsafe_identifiers() -> None:
    with pytest.raises(ValueError):
        rls.build_strict_policy_sql("documents; DROP TABLE users")
    with pytest.raises(ValueError):
        rls.build_lookup_policy_sql("Users")
