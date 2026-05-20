from importlib import util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

INITIAL_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260507_0001_initial_schema.py"
)
AGENT_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260520_0002_agent_run_persistence.py"
)


def _load_migration(path: Path, module_name: str):
    spec = util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load migration module: {path.name}")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_persistence_migration_upgrade_and_downgrade_smoke() -> None:
    initial_migration = _load_migration(INITIAL_MIGRATION_PATH, "migration_20260507_0001")
    agent_migration = _load_migration(AGENT_MIGRATION_PATH, "migration_20260520_0002")

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            initial_migration.upgrade()
            agent_migration.upgrade()

            inspector = sa.inspect(connection)
            table_names = set(inspector.get_table_names())
            assert {
                "agent_runs",
                "agent_steps",
                "agent_tool_calls",
                "agent_approvals",
            }.issubset(table_names)

            run_indexes = {index["name"] for index in inspector.get_indexes("agent_runs")}
            assert "idx_agent_runs_org_status" in run_indexes
            assert "idx_agent_runs_org_user_created" in run_indexes

            call_indexes = {index["name"] for index in inspector.get_indexes("agent_tool_calls")}
            assert "idx_agent_tool_calls_org_status" in call_indexes
            assert "idx_agent_tool_calls_run_status" in call_indexes

            approval_indexes = {index["name"] for index in inspector.get_indexes("agent_approvals")}
            assert "idx_agent_approvals_org_status" in approval_indexes
            assert "idx_agent_approvals_run_status" in approval_indexes

            agent_migration.downgrade()
            initial_migration.downgrade()
            assert sa.inspect(connection).get_table_names() == []
