import os
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "clerk")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.com/.well-known/jwks.json")
os.environ.setdefault("CLERK_JWT_ISSUER", "https://clerk.example.com")
os.environ.setdefault("CLERK_JWT_AUDIENCE", "rudix-api")

from app.core.config import settings
from app.core.document_errors import decode_document_error
from app.models.enums import DocumentStatus, EvaluationRunStatus, GraphExtractionStatus
from app.workers import document_tasks, evaluation_tasks
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app


@pytest.fixture
def eager_celery() -> None:
    always_eager = celery_app.conf.task_always_eager
    eager_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    try:
        yield
    finally:
        celery_app.conf.task_always_eager = always_eager
        celery_app.conf.task_eager_propagates = eager_propagates


def test_celery_configuration_and_routes_are_wired() -> None:
    assert celery_app.conf.task_default_queue == settings.celery_task_default_queue
    assert (
        celery_app.conf.task_routes["documents.process"]["queue"]
        == settings.celery_queue_documents_processing
    )
    assert (
        celery_app.conf.task_routes["documents.delete"]["queue"]
        == settings.celery_queue_documents_deletion
    )
    assert (
        celery_app.conf.task_routes["documents.reindex"]["queue"]
        == settings.celery_queue_documents_reindex
    )
    assert (
        celery_app.conf.task_routes["evaluations.run"]["queue"] == settings.celery_queue_evaluations
    )

    registered = set(celery_app.tasks.keys())
    assert "documents.process" in registered
    assert "documents.delete" in registered
    assert "documents.reindex" in registered
    assert "evaluations.run" in registered


def test_retry_policy_retries_transient_failures(eager_celery: None) -> None:
    attempts = {"count": 0}
    task_name = f"tests.retry.{uuid4()}"

    @celery_app.task(bind=True, base=RudixTask, name=task_name)
    def flaky_task(self: RudixTask) -> int:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TransientTaskError("temporary")
        return attempts["count"]

    result = flaky_task.delay().get(timeout=5)
    assert result == 3
    assert attempts["count"] == 3


def test_process_document_is_idempotent_when_already_indexed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.indexed.value,
    )
    monkeypatch.setattr(
        document_tasks,
        "set_document_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not update status")),
    )

    result = document_tasks.process_document.run("doc-1")
    assert result["status"] == "skipped"


def test_process_document_is_idempotent_when_already_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.processing.value,
    )
    monkeypatch.setattr(
        document_tasks,
        "set_document_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not update status")),
    )

    result = document_tasks.process_document.run("doc-1")
    assert result["status"] == "skipped"


def test_process_document_extracts_and_sets_indexed_status(monkeypatch: pytest.MonkeyPatch) -> None:
    status_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.uploaded.value,
    )

    def _set_document_status(
        document_id: str, *, status: DocumentStatus, error_message: str | None = None
    ) -> bool:
        del error_message
        status_calls.append((document_id, status.value))
        return True

    async def _extract_and_store(_: str, **__: object) -> tuple[int, int, object, object]:
        class _Stats:
            pages_modified = 2

            @staticmethod
            def as_log_fields() -> dict[str, int]:
                return {
                    "cleaning_pages_total": 4,
                    "cleaning_pages_modified": 2,
                    "cleaning_null_bytes_removed": 1,
                    "cleaning_invalid_characters_removed": 0,
                    "cleaning_whitespace_runs_collapsed": 3,
                    "cleaning_blank_lines_collapsed": 1,
                    "cleaning_chars_before": 120,
                    "cleaning_chars_after": 110,
                }

        class _EmbeddingResult:
            batch_count = 2
            retry_count = 1
            input_tokens = 400
            total_tokens = 400
            latency_ms = 150
            approximate_cost_usd = Decimal("0.000008")

        return 4, 9, _Stats(), _EmbeddingResult()

    monkeypatch.setattr(document_tasks, "set_document_status", _set_document_status)
    monkeypatch.setattr(
        document_tasks, "_extract_and_store_document_pages_async", _extract_and_store
    )

    result = document_tasks.process_document.run("doc-1")
    assert result["status"] == DocumentStatus.indexed.value
    assert result["page_count"] == 4
    assert result["chunk_count"] == 9
    assert result["embedding_batch_count"] == 2
    assert result["embedding_retry_count"] == 1
    assert result["cleaning_pages_modified"] == 2
    assert status_calls == [("doc-1", DocumentStatus.processing.value)]


@pytest.mark.asyncio
async def test_graph_extraction_helper_updates_status_and_prunes_existing_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        uploaded_by_user_id=uuid4(),
        filename="policy.pdf",
        language="en",
        graph_extraction_run_id=uuid4(),
    )
    chunk_pairs = [(0, "Alpha mentions Beta."), (1, "Beta is covered.")]
    chunk_id_by_index = {0: uuid4(), 1: uuid4()}
    page_by_index = {0: 1, 1: 2}
    graph_status_calls: list[tuple[str, str, str | None]] = []
    graph_calls: list[tuple[str, dict[str, object]]] = []
    entity_id = uuid4()
    relation_id = uuid4()

    class FakeRecorder:
        async def emit_stage(self, **_: object) -> None:
            return None

    async def _set_graph_status(
        document_id: UUID,
        *,
        status: str,
        run_id: UUID | None = None,
    ) -> None:
        graph_status_calls.append((str(document_id), status, str(run_id) if run_id else None))

    async def _clear_document_graph_facts(**kwargs: object) -> None:
        graph_calls.append(("clear", kwargs))

    async def _start_extraction_run(**kwargs: object) -> None:
        graph_calls.append(("start_run", kwargs))

    async def _finish_extraction_run(**kwargs: object) -> None:
        graph_calls.append(("finish_run", kwargs))

    async def _upsert_entity(**kwargs: object) -> None:
        graph_calls.append(("entity", kwargs))

    async def _upsert_alias(**kwargs: object) -> None:
        graph_calls.append(("alias", kwargs))

    async def _link_evidence(**kwargs: object) -> None:
        graph_calls.append(("evidence", kwargs))

    async def _create_relation(**kwargs: object) -> None:
        graph_calls.append(("relation", kwargs))

    async def _extract_entities(**_: object) -> object:
        entity = SimpleNamespace(
            entity_id=entity_id,
            type="policy",
            name="Alpha",
            original_name="Alpha",
            aliases=["Alpha Policy"],
            language="en",
            confidence=0.93,
            evidence_span="Alpha mentions Beta.",
            source_chunk_index=0,
        )
        return SimpleNamespace(
            entities=[entity],
            batch_count=1,
            total_chunks=2,
            validation_errors=0,
            llm_errors=0,
        )

    async def _extract_relations(**_: object) -> object:
        relation = SimpleNamespace(
            relation_id=relation_id,
            from_entity_id=entity_id,
            to_entity_id=uuid4(),
            rel_type="RELATES_TO",
            confidence=0.82,
            evidence_span="Alpha mentions Beta.",
            source_chunk_index=0,
        )
        return SimpleNamespace(
            relations=[relation],
            batch_count=1,
            skipped_unknown_entity=0,
            validation_errors=0,
            llm_errors=0,
        )

    monkeypatch.setattr(settings, "feature_enable_entity_resolution", False)
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "feature_enable_entity_extraction", True)
    monkeypatch.setattr(settings, "feature_enable_relation_extraction", True)
    monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _set_graph_status)
    monkeypatch.setattr(
        document_tasks._graph_service,
        "clear_document_graph_facts",
        _clear_document_graph_facts,
    )
    monkeypatch.setattr(
        document_tasks._graph_service, "start_extraction_run", _start_extraction_run
    )
    monkeypatch.setattr(
        document_tasks._graph_service,
        "finish_extraction_run",
        _finish_extraction_run,
    )
    monkeypatch.setattr(document_tasks._graph_service, "upsert_entity", _upsert_entity)
    monkeypatch.setattr(document_tasks._graph_service, "upsert_entity_alias", _upsert_alias)
    monkeypatch.setattr(document_tasks._graph_service, "link_evidence", _link_evidence)
    monkeypatch.setattr(
        document_tasks._graph_service,
        "create_relation_with_evidence",
        _create_relation,
    )
    monkeypatch.setattr(
        document_tasks._entity_extraction_service,
        "extract_from_chunks",
        _extract_entities,
    )
    monkeypatch.setattr(
        document_tasks._relation_extraction_service,
        "extract_from_chunks",
        _extract_relations,
    )

    result = await document_tasks._run_document_graph_extraction_async(
        document,
        request_id="req-graph-1",
        organization_id=str(document.organization_id),
        user_id=str(document.uploaded_by_user_id),
        pipeline_type="document.process",
        chunk_pairs=chunk_pairs,
        chunk_id_by_index=chunk_id_by_index,
        page_by_index=page_by_index,
        pipeline_recorder=FakeRecorder(),
        clear_existing_facts=True,
    )

    assert result == {"entity_count": 1, "relation_count": 1}
    assert graph_status_calls[0][1] == "extracting"
    assert graph_status_calls[-1][1] == "completed"
    assert any(
        name == "clear" and kwargs.get("extraction_run_id") == document.graph_extraction_run_id
        for name, kwargs in graph_calls
    )
    assert any(name == "entity" for name, _ in graph_calls)
    assert any(name == "alias" for name, _ in graph_calls)
    assert any(name == "evidence" for name, _ in graph_calls)
    assert any(name == "relation" for name, _ in graph_calls)


def test_process_document_marks_graph_pending_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = str(uuid4())
    graph_status_calls: list[tuple[str, str, str | None]] = []

    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.uploaded.value,
    )

    def _set_document_status(
        document_id: str, *, status: DocumentStatus, error_message: str | None = None
    ) -> bool:
        del error_message
        assert status == DocumentStatus.processing
        return True

    async def _set_graph_status(
        document_id: UUID,
        *,
        status: str,
        run_id: UUID | None = None,
    ) -> None:
        graph_status_calls.append((str(document_id), status, str(run_id) if run_id else None))

    async def _extract_and_store(_: str, **__: object) -> tuple[int, int, object, object]:
        class _Stats:
            pages_modified = 0

            @staticmethod
            def as_log_fields() -> dict[str, int]:
                return {
                    "cleaning_pages_total": 1,
                    "cleaning_pages_modified": 0,
                    "cleaning_null_bytes_removed": 0,
                    "cleaning_invalid_characters_removed": 0,
                    "cleaning_whitespace_runs_collapsed": 0,
                    "cleaning_blank_lines_collapsed": 0,
                    "cleaning_chars_before": 10,
                    "cleaning_chars_after": 10,
                }

        class _EmbeddingResult:
            batch_count = 1
            retry_count = 0
            input_tokens = 10
            total_tokens = 10
            latency_ms = 5
            approximate_cost_usd = Decimal("0.000001")

        return 1, 1, _Stats(), _EmbeddingResult()

    monkeypatch.setattr(document_tasks, "set_document_status", _set_document_status)
    monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _set_graph_status)
    monkeypatch.setattr(
        document_tasks, "_extract_and_store_document_pages_async", _extract_and_store
    )

    result = document_tasks.process_document.run(document_id)
    assert result["status"] == DocumentStatus.indexed.value
    assert graph_status_calls == [(document_id, GraphExtractionStatus.pending.value, None)]


def test_reindex_document_marks_graph_pending_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = str(uuid4())
    graph_status_calls: list[tuple[str, str, str | None]] = []

    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.indexed.value,
    )

    def _set_document_status(
        document_id: str, *, status: DocumentStatus, error_message: str | None = None
    ) -> bool:
        del error_message
        assert status == DocumentStatus.processing
        return True

    async def _set_graph_status(
        document_id: UUID,
        *,
        status: str,
        run_id: UUID | None = None,
    ) -> None:
        graph_status_calls.append((str(document_id), status, str(run_id) if run_id else None))

    async def _extract_and_store(_: str, **__: object) -> tuple[int, int, object, object]:
        class _Stats:
            pages_modified = 0

            @staticmethod
            def as_log_fields() -> dict[str, int]:
                return {
                    "cleaning_pages_total": 1,
                    "cleaning_pages_modified": 0,
                    "cleaning_null_bytes_removed": 0,
                    "cleaning_invalid_characters_removed": 0,
                    "cleaning_whitespace_runs_collapsed": 0,
                    "cleaning_blank_lines_collapsed": 0,
                    "cleaning_chars_before": 10,
                    "cleaning_chars_after": 10,
                }

        class _EmbeddingResult:
            batch_count = 1
            retry_count = 0
            input_tokens = 10
            total_tokens = 10
            latency_ms = 5
            approximate_cost_usd = Decimal("0.000001")

        return 1, 1, _Stats(), _EmbeddingResult()

    monkeypatch.setattr(document_tasks, "set_document_status", _set_document_status)
    monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _set_graph_status)
    monkeypatch.setattr(
        document_tasks, "_extract_and_store_document_pages_async", _extract_and_store
    )

    result = document_tasks.reindex_document.run(document_id)
    assert result["status"] == DocumentStatus.indexed.value
    assert graph_status_calls == [(document_id, GraphExtractionStatus.pending.value, None)]


def test_graph_reindex_task_dispatches_rebuild_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.indexed.value,
    )

    async def _rebuild(document_id: str, **_: object) -> dict[str, str | int]:
        assert document_id == "doc-graph-1"
        return {
            "document_id": document_id,
            "status": "completed",
            "chunk_count": 4,
            "entity_count": 2,
            "relation_count": 1,
        }

    monkeypatch.setattr(document_tasks, "_reindex_document_graph_async", _rebuild)

    result = document_tasks.reindex_document_graph.run("doc-graph-1")
    assert result["status"] == "completed"
    assert result["chunk_count"] == 4


def test_document_task_terminal_failure_marks_document_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def _set_document_status(
        document_id: str, *, status: DocumentStatus, error_message: str | None = None
    ) -> bool:
        captured["document_id"] = document_id
        captured["status"] = status.value
        captured["error_message"] = error_message or ""
        return True

    monkeypatch.setattr(document_tasks, "set_document_status", _set_document_status)
    document_tasks.process_document.on_terminal_failure(
        exc=RuntimeError("boom"),
        args=("doc-1",),
        kwargs={},
    )

    assert captured["document_id"] == "doc-1"
    assert captured["status"] == DocumentStatus.failed.value
    message, details = decode_document_error(captured["error_message"])
    assert message == "boom"
    assert details is not None
    assert details["code"] == "UNEXPECTED_ERROR"
    assert details["retryable"] is False


def test_process_document_retries_transient_failures_without_failing_status(
    eager_celery: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}
    status_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.uploaded.value,
    )

    def _set_document_status(
        document_id: str, *, status: DocumentStatus, error_message: str | None = None
    ) -> bool:
        del error_message
        status_calls.append((document_id, status.value))
        return True

    async def _extract_and_store(_: str, **__: object) -> tuple[int, int, object, object]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise document_tasks.DocumentPipelineTransientError(
                stage="embed",
                code="EMBEDDING_FAILED_TRANSIENT",
                category="infrastructure",
                message="embedding timeout",
            )

        class _Stats:
            pages_modified = 0

            @staticmethod
            def as_log_fields() -> dict[str, int]:
                return {
                    "cleaning_pages_total": 1,
                    "cleaning_pages_modified": 0,
                    "cleaning_null_bytes_removed": 0,
                    "cleaning_invalid_characters_removed": 0,
                    "cleaning_whitespace_runs_collapsed": 0,
                    "cleaning_blank_lines_collapsed": 0,
                    "cleaning_chars_before": 10,
                    "cleaning_chars_after": 10,
                }

        class _EmbeddingResult:
            batch_count = 1
            retry_count = 0
            input_tokens = 10
            total_tokens = 10
            latency_ms = 5
            approximate_cost_usd = Decimal("0.000001")

        return 1, 1, _Stats(), _EmbeddingResult()

    monkeypatch.setattr(document_tasks, "set_document_status", _set_document_status)
    monkeypatch.setattr(
        document_tasks, "_extract_and_store_document_pages_async", _extract_and_store
    )

    result = document_tasks.process_document.delay("doc-1").get(timeout=5)
    assert result["status"] == DocumentStatus.indexed.value
    assert attempts["count"] == 2
    assert status_calls == [
        ("doc-1", DocumentStatus.processing.value),
        ("doc-1", DocumentStatus.processing.value),
    ]


def test_reindex_document_runs_pipeline_and_emits_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    status_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.indexed.value,
    )

    def _set_document_status(
        document_id: str, *, status: DocumentStatus, error_message: str | None = None
    ) -> bool:
        del error_message
        status_calls.append((document_id, status.value))
        return True

    async def _extract_and_store(_: str, **__: object) -> tuple[int, int, object, object]:
        class _Stats:
            pages_modified = 1

            @staticmethod
            def as_log_fields() -> dict[str, int]:
                return {
                    "cleaning_pages_total": 2,
                    "cleaning_pages_modified": 1,
                    "cleaning_null_bytes_removed": 0,
                    "cleaning_invalid_characters_removed": 0,
                    "cleaning_whitespace_runs_collapsed": 1,
                    "cleaning_blank_lines_collapsed": 0,
                    "cleaning_chars_before": 42,
                    "cleaning_chars_after": 40,
                }

        class _EmbeddingResult:
            batch_count = 1
            retry_count = 0
            input_tokens = 60
            total_tokens = 60
            latency_ms = 11
            approximate_cost_usd = Decimal("0.000002")

        return 2, 3, _Stats(), _EmbeddingResult()

    monkeypatch.setattr(document_tasks, "set_document_status", _set_document_status)
    monkeypatch.setattr(
        document_tasks, "_extract_and_store_document_pages_async", _extract_and_store
    )

    result = document_tasks.reindex_document.run("doc-1")
    assert result["status"] == DocumentStatus.indexed.value
    assert result["page_count"] == 2
    assert result["chunk_count"] == 3
    assert result["index_version"] == settings.document_index_version
    assert status_calls == [("doc-1", DocumentStatus.processing.value)]


def test_reindex_document_continues_when_already_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.processing.value,
    )
    monkeypatch.setattr(
        document_tasks,
        "set_document_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not set status again")
        ),
    )

    async def _extract_and_store(_: str, **__: object) -> tuple[int, int, object, object]:
        class _Stats:
            pages_modified = 0

            @staticmethod
            def as_log_fields() -> dict[str, int]:
                return {
                    "cleaning_pages_total": 1,
                    "cleaning_pages_modified": 0,
                    "cleaning_null_bytes_removed": 0,
                    "cleaning_invalid_characters_removed": 0,
                    "cleaning_whitespace_runs_collapsed": 0,
                    "cleaning_blank_lines_collapsed": 0,
                    "cleaning_chars_before": 10,
                    "cleaning_chars_after": 10,
                }

        class _EmbeddingResult:
            batch_count = 1
            retry_count = 0
            input_tokens = 10
            total_tokens = 10
            latency_ms = 5
            approximate_cost_usd = Decimal("0.000001")

        return 1, 1, _Stats(), _EmbeddingResult()

    monkeypatch.setattr(
        document_tasks, "_extract_and_store_document_pages_async", _extract_and_store
    )

    result = document_tasks.reindex_document.run("doc-1")
    assert result["status"] == DocumentStatus.indexed.value
    assert result["page_count"] == 1
    assert result["chunk_count"] == 1


def test_reindex_document_rejects_deleting_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        document_tasks,
        "get_document_status",
        lambda _: DocumentStatus.deleting.value,
    )

    with pytest.raises(PermanentTaskError, match="Cannot reindex deleting document"):
        document_tasks.reindex_document.run("doc-1")


def test_evaluation_run_transitions_status(monkeypatch: pytest.MonkeyPatch) -> None:
    transitions: list[str] = []

    monkeypatch.setattr(
        evaluation_tasks,
        "get_evaluation_status",
        lambda _: EvaluationRunStatus.queued.value,
    )

    def _set_eval_status(
        evaluation_run_id: str,
        *,
        status: EvaluationRunStatus,
        mark_started: bool = False,
        mark_completed: bool = False,
    ) -> bool:
        del evaluation_run_id, mark_started, mark_completed
        transitions.append(status.value)
        return True

    monkeypatch.setattr(evaluation_tasks, "set_evaluation_status", _set_eval_status)
    monkeypatch.setattr(
        evaluation_tasks,
        "_run_evaluation_async",
        lambda *_args, **_kwargs: _completed_summary(),
    )

    async def _completed_summary() -> dict[str, object]:
        return {
            "evaluation_run_id": "eval-1",
            "question_total_count": 3,
            "question_success_count": 3,
            "question_failure_count": 0,
            "all_questions_failed": False,
        }

    result = evaluation_tasks.run_evaluation.run("eval-1")
    assert result["status"] == EvaluationRunStatus.completed.value
    assert transitions == [EvaluationRunStatus.running.value, EvaluationRunStatus.completed.value]


def test_evaluation_run_marks_failed_when_all_questions_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transitions: list[str] = []
    monkeypatch.setattr(
        evaluation_tasks,
        "get_evaluation_status",
        lambda _: EvaluationRunStatus.queued.value,
    )

    def _set_eval_status(
        evaluation_run_id: str,
        *,
        status: EvaluationRunStatus,
        mark_started: bool = False,
        mark_completed: bool = False,
    ) -> bool:
        del evaluation_run_id, mark_started, mark_completed
        transitions.append(status.value)
        return True

    monkeypatch.setattr(evaluation_tasks, "set_evaluation_status", _set_eval_status)
    monkeypatch.setattr(
        evaluation_tasks,
        "_run_evaluation_async",
        lambda *_args, **_kwargs: _failed_summary(),
    )

    async def _failed_summary() -> dict[str, object]:
        return {
            "evaluation_run_id": "eval-1",
            "question_total_count": 2,
            "question_success_count": 0,
            "question_failure_count": 2,
            "all_questions_failed": True,
        }

    result = evaluation_tasks.run_evaluation.run("eval-1")
    assert result["status"] == EvaluationRunStatus.failed.value
    assert transitions == [EvaluationRunStatus.running.value, EvaluationRunStatus.failed.value]
