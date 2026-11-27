"""The document_tasks facade keeps its public and rebindable names (R06-01, contract 4.2.2)."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
)
from sqlalchemy import func, select

from app.models.document_processing import DocumentProcessingStage
from app.workers import document_tasks
from app.workers.celery_app import celery_app
from app.workers.ingestion import deps as deps_module
from app.workers.ingestion.deps import REBINDABLE_FACADE_NAMES, current_deps

CONTRACT_REBINDABLE = (
    "SessionLocal",
    "_document_repository",
    "_qdrant_service",
    "_embedding_service",
    "_chunking_service",
    "_graph_service",
    "_entity_extraction_service",
    "_relation_extraction_service",
    "_usage_repository",
    "claim_document_for_processing",
    "set_document_status",
    "mark_document_failed",
    "get_document_status",
    "log_document_event",
    "log_chunking_event",
    "_record_worker_audit",
    "_record_worker_audit_async",
    "_update_document_graph_status_async",
    "_run_document_graph_extraction_async",
    "_reindex_document_graph_async",
    "_run",
)
CONTRACT_CALLABLES = (
    "_extract_and_store_document_pages_async",
    "_delete_document_assets_async",
    "_backfill_dispatch_async",
    "_make_chunking_service",
    "DocumentPipelinePermanentError",
    "DocumentPipelineTransientError",
)
TASKS = {
    "documents.process": "process_document",
    "documents.reindex": "reindex_document",
    "documents.delete": "delete_document",
    "documents.graph_reindex": "reindex_document_graph",
    "documents.backfill": "backfill_documents",
}
MODULE_SINGLETONS = (
    "_connector_repository",
    "_pipeline_repository",
    "_audit_log_service",
    "_source_provenance_service",
    "_entity_resolution_service",
    "_ocr_quality_service",
)


@pytest.mark.parametrize("name", CONTRACT_REBINDABLE + CONTRACT_CALLABLES + MODULE_SINGLETONS)
def test_facade_keeps_every_contract_name(name: str) -> None:
    assert hasattr(document_tasks, name), name


def test_every_contract_rebindable_is_read_through_current_deps() -> None:
    assert set(CONTRACT_REBINDABLE) <= set(REBINDABLE_FACADE_NAMES)
    assert set(REBINDABLE_FACADE_NAMES) <= set(dir(document_tasks))


def test_current_deps_reads_rebinding_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = object()
    for name in REBINDABLE_FACADE_NAMES:
        monkeypatch.setattr(document_tasks, name, marker)
    deps = current_deps()
    for field in deps_module._FACADE_NAMES:
        assert getattr(deps, field) is marker, field


def test_task_names_and_signatures_are_unchanged() -> None:
    expected_params = {
        "process_document": [
            "document_id",
            "request_id",
            "organization_id",
            "user_id",
            "force",
            "chunking_profile_config",
            # R06-01 part 2 (additive): reaper resume and failed-job retry.
            "resume_run_id",
            "job_id",
        ],
        "reindex_document": [
            "document_id",
            "request_id",
            "organization_id",
            "user_id",
            "chunking_profile_config",
            "force",
            "resume_run_id",
            "job_id",
        ],
        "delete_document": ["document_id", "request_id", "organization_id", "user_id"],
        "reindex_document_graph": [
            "document_id",
            "request_id",
            "organization_id",
            "user_id",
            # R06-01 part 2: graph task failures record documents.graph_reindex; the
            # failed-job retry sends job_id.
            "job_id",
        ],
        "backfill_documents": [
            "organization_id",
            "chunking_profile_config",
            "request_id",
            "user_id",
        ],
    }
    for task_name, attribute in TASKS.items():
        task = getattr(document_tasks, attribute)
        assert task.name == task_name
        assert task_name in celery_app.tasks
        params = list(inspect.signature(task.run).parameters)
        assert params == expected_params[attribute], attribute


def test_extract_and_store_keeps_its_keywords() -> None:
    params = inspect.signature(document_tasks._extract_and_store_document_pages_async).parameters
    for name in (
        "request_id",
        "organization_id",
        "user_id",
        "pipeline_type",
        "chunking_service",
        "profile_source",
        "persist_document_state",
        "persist_document_pages",
        "record_usage_event",
    ):
        assert name in params, name


def test_facade_stays_under_500_lines() -> None:
    lines = Path(document_tasks.__file__).read_text(encoding="utf-8").splitlines()
    assert len(lines) < 500


def test_rebinding_on_the_facade_reaches_the_stages(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ingestion_env
    # ingestion_env rebinds SessionLocal, _qdrant_service, _embedding_service and
    # _graph_service on the facade; a graph run proves the graph service is reached.
    monkeypatch.setattr("app.core.config.settings.enterprise_graph_enabled", True)
    monkeypatch.setattr("app.core.config.settings.feature_enable_entity_extraction", True)

    class _NoEntities:
        async def extract_from_chunks(self, **_: Any) -> Any:
            return type(
                "R",
                (),
                {
                    "entities": [],
                    "batch_count": 1,
                    "validation_errors": 0,
                    "llm_errors": 0,
                    "total_chunks": 1,
                },
            )()

    monkeypatch.setattr(document_tasks, "_entity_extraction_service", _NoEntities())
    env.set_content(b"Rebinding reaches every stage of the staged ingestion run.")
    seeded = env.seed()
    result = env.run_task(document_tasks.process_document, seeded.document_id, task_id="compat")

    assert result["status"] == "indexed"
    assert env.fakes.minio.reads == 1
    assert len(env.fakes.embeddings.batches) == 1
    assert len(env.fakes.qdrant.upserts) == 1
    assert env.fakes.qdrant.deletes == [{"index_version": "v1"}]
    assert "start_extraction_run" in env.fakes.graph.calls

    async def _stage_rows() -> int:
        async with env.factory() as session:
            stmt = select(func.count()).where(
                DocumentProcessingStage.document_id == seeded.document_id
            )
            return int((await session.execute(stmt)).scalar_one())

    # The rebound SessionLocal (the test database) holds the stage rows.
    assert env.run_async(_stage_rows()) == 8
