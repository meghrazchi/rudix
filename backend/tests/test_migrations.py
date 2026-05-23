from importlib import util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260507_0001_initial_schema.py"
)


def _load_initial_migration():
    spec = util.spec_from_file_location("migration_20260507_0001", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load initial migration module")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initial_migration_upgrade_and_downgrade_smoke() -> None:
    migration_module = _load_initial_migration()
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration_module.upgrade()

            inspector = sa.inspect(connection)
            table_names = set(inspector.get_table_names())
            assert {
                "organizations",
                "users",
                "organization_members",
                "documents",
                "document_pages",
                "document_chunks",
                "chat_sessions",
                "chat_messages",
                "citations",
                "evaluation_sets",
                "evaluation_questions",
                "evaluation_runs",
                "evaluation_results",
                "pipeline_runs",
                "pipeline_events",
                "usage_events",
                "audit_logs",
            }.issubset(table_names)

            document_indexes = {index["name"] for index in inspector.get_indexes("documents")}
            assert "idx_documents_org_status" in document_indexes

            chunk_indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
            assert "idx_chunks_document_id" in chunk_indexes
            assert "idx_chunks_qdrant_point_id" in chunk_indexes

            pipeline_run_indexes = {
                index["name"] for index in inspector.get_indexes("pipeline_runs")
            }
            assert "idx_pipeline_runs_org_created" in pipeline_run_indexes

            pipeline_event_indexes = {
                index["name"] for index in inspector.get_indexes("pipeline_events")
            }
            assert "idx_pipeline_events_run_sequence" in pipeline_event_indexes

            migration_module.downgrade()
            assert sa.inspect(connection).get_table_names() == []
