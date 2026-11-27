"""Index migrations 20261127_0001..0003 (R04-02): SQLite branch and PostgreSQL recovery."""

from collections.abc import Callable
from importlib import util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from tests.conftest import build_sqlite_template

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_FILES = (
    "20261127_0001_chat_activity_indexes.py",
    "20261127_0002_document_connector_indexes.py",
    "20261127_0003_identity_log_indexes.py",
)


def _load(filename: str) -> ModuleType:
    spec = util.spec_from_file_location(f"migration_{filename[:13]}", VERSIONS_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load migration {filename}")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULES = tuple(_load(filename) for filename in MIGRATION_FILES)


def _run(connection: Connection, action: Callable[[], None]) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        action()


def _index_names(connection: Connection, table: str) -> set[str]:
    return {str(index["name"]) for index in sa.inspect(connection).get_indexes(table)}


def test_revision_chain_is_linear() -> None:
    assert [(m.revision, m.down_revision) for m in MODULES] == [
        ("20261127_0001", "20261126_0001"),
        ("20261127_0002", "20261127_0001"),
        ("20261127_0003", "20261127_0002"),
    ]


def test_model_indexes_match_migrations() -> None:
    """Same names, tables, and column order/direction in the models as in the migrations."""
    tables = {table.name: table for table in Base.metadata.tables.values()}
    for module in MODULES:
        for name, table, columns in module.INDEXES:
            index = next(i for i in tables[table].indexes if i.name == name)
            rendered = [
                expr.name if isinstance(expr, sa.Column) else str(expr)
                for expr in index.expressions
            ]
            assert rendered == list(columns), name


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.revision)
def test_sqlite_upgrade_and_downgrade(tmp_path: Path, module: ModuleType) -> None:
    engine = sa.create_engine(f"sqlite:///{build_sqlite_template(tmp_path / 'schema.db')}")
    try:
        with engine.begin() as connection:
            # The template already has the model indexes; start from the pre-migration state.
            _run(connection, module.downgrade)
            for name, table, _ in module.INDEXES:
                assert name not in _index_names(connection, table)

            _run(connection, module.upgrade)
            for name, table, _ in module.INDEXES:
                assert name in _index_names(connection, table)
    finally:
        engine.dispose()


_INDEX_STATE_SQL = sa.text(
    "SELECT i.indexrelid::bigint AS oid, i.indisvalid AS valid FROM pg_index i "
    "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
)


async def _index_state(url: str, name: str) -> Any:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(_INDEX_STATE_SQL, {"name": name})).one_or_none()
    finally:
        await engine.dispose()


async def _run_pg(url: str, action: Callable[[], None]) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.run_sync(_run, action)
            await conn.commit()
    finally:
        await engine.dispose()


async def _execute_autocommit(url: str, sql: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text(sql))
    finally:
        await engine.dispose()


@pytest.mark.requires_postgres
async def test_postgres_upgrade_rebuilds_invalid_index_and_keeps_valid_ones(
    pg_migrated_url: str,
) -> None:
    module = MODULES[0]
    target, untouched = "idx_citations_chunk", "idx_citations_document"
    before = await _index_state(pg_migrated_url, untouched)
    # Simulates a CREATE INDEX CONCURRENTLY that failed half way (needs a superuser).
    try:
        await _execute_autocommit(
            pg_migrated_url,
            f"UPDATE pg_index SET indisvalid = false WHERE indexrelid = '{target}'::regclass",
        )
    except sa.exc.DBAPIError:
        pytest.skip("Marking an index invalid needs a superuser on TEST_DATABASE_URL")
    invalid = await _index_state(pg_migrated_url, target)
    assert invalid is not None and invalid.valid is False

    await _run_pg(pg_migrated_url, module.upgrade)

    rebuilt = await _index_state(pg_migrated_url, target)
    assert rebuilt.valid is True
    assert rebuilt.oid != invalid.oid
    assert (await _index_state(pg_migrated_url, untouched)).oid == before.oid


@pytest.mark.requires_postgres
async def test_postgres_downgrade_then_upgrade_round_trip(pg_migrated_url: str) -> None:
    module = MODULES[2]
    try:
        await _run_pg(pg_migrated_url, module.downgrade)
        for name, _, _ in module.INDEXES:
            assert await _index_state(pg_migrated_url, name) is None
    finally:
        await _run_pg(pg_migrated_url, module.upgrade)
    for name, _, _ in module.INDEXES:
        state = await _index_state(pg_migrated_url, name)
        assert state is not None and state.valid is True
