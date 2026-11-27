"""Inline graph extraction paths moved to app/workers/ingestion/graph.py (R06-01)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from ingestion_golden_support import (
    FakeEmbeddings,  # noqa: F401  (sets the strict-settings environment first)
)

from app.core.config import settings
from app.workers import document_tasks
from app.workers.ingestion.errors import DocumentPipelineTransientError


class _Graph:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def resolve_entity(self, **_: Any) -> Any:
        self.calls.append("resolve")
        return SimpleNamespace(
            canonical_entity_id=uuid4(),
            status="matched",
            candidate_score=0.9,
            canonical_name="Alpha Canonical",
        )

    def __getattr__(self, name: str) -> Any:
        async def _call(**_: Any) -> None:
            self.calls.append(name)

        return _call


def _entities(**_: Any) -> Any:
    entity = SimpleNamespace(
        entity_id=uuid4(),
        type="policy",
        name="Alpha",
        original_name="Alpha",
        aliases=[],
        language="en",
        confidence=0.9,
        evidence_span="Alpha",
        source_chunk_index=0,
    )
    return SimpleNamespace(
        entities=[entity], batch_count=1, total_chunks=1, validation_errors=0, llm_errors=0
    )


async def _run(monkeypatch: pytest.MonkeyPatch, *, strict: bool) -> tuple[Any, list[str]]:
    statuses: list[str] = []
    graph = _Graph()

    async def _status(document_id: UUID, *, status: str, run_id: UUID | None = None) -> None:
        statuses.append(status)

    async def _extract(**kwargs: Any) -> Any:
        return _entities(**kwargs)

    async def _relations_fail(**_: Any) -> Any:
        raise RuntimeError("relation provider down")

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "feature_enable_entity_extraction", True)
    monkeypatch.setattr(settings, "feature_enable_entity_resolution", True)
    monkeypatch.setattr(settings, "feature_enable_relation_extraction", True)
    monkeypatch.setattr(settings, "relation_extraction_strict_mode", strict)
    monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _status)
    monkeypatch.setattr(document_tasks, "_graph_service", graph)
    monkeypatch.setattr(
        document_tasks, "_entity_extraction_service", SimpleNamespace(extract_from_chunks=_extract)
    )
    monkeypatch.setattr(
        document_tasks,
        "_relation_extraction_service",
        SimpleNamespace(extract_from_chunks=_relations_fail),
    )

    class _Recorder:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        async def emit_stage(self, *, stage: str, stage_status: str, **_: Any) -> None:
            self.events.append((stage, stage_status))

    recorder = _Recorder()
    document = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        uploaded_by_user_id=uuid4(),
        filename="g.txt",
        language="en",
        graph_extraction_run_id=None,
    )
    result = await document_tasks._run_document_graph_extraction_async(
        document,
        request_id=None,
        organization_id=None,
        user_id=None,
        pipeline_type="document.process",
        chunk_pairs=[(0, "Alpha")],
        chunk_id_by_index={0: uuid4()},
        page_by_index={0: 1},
        pipeline_recorder=recorder,  # type: ignore[arg-type]
        clear_existing_facts=True,
    )
    return (result, recorder.events, graph.calls, statuses), statuses


async def test_relation_failure_is_recorded_in_lenient_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (result, events, calls, statuses), _ = await _run(monkeypatch, strict=False)
    assert result == {"entity_count": 1, "relation_count": 0}
    assert ("extract_relations", "failed") in events
    assert "resolve" in calls and "upsert_entity" in calls
    assert statuses[-1] == "completed"


async def test_relation_failure_fails_the_run_in_strict_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(DocumentPipelineTransientError) as raised:
        await _run(monkeypatch, strict=True)
    assert raised.value.error_details["code"] == "RELATION_EXTRACTION_FAILED"


async def test_graph_disabled_marks_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses: list[str] = []

    async def _status(document_id: UUID, *, status: str, run_id: UUID | None = None) -> None:
        statuses.append(status)

    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _status)
    document = SimpleNamespace(id=uuid4(), organization_id=uuid4(), uploaded_by_user_id=uuid4())
    result = await document_tasks._run_document_graph_extraction_async(
        document,
        request_id=None,
        organization_id=None,
        user_id=None,
        pipeline_type="document.process",
        chunk_pairs=[],
        chunk_id_by_index={},
        page_by_index={},
    )
    assert result == {"entity_count": 0, "relation_count": 0}
    assert statuses == ["skipped"]
