"""The evaluation_tasks facade keeps its task, names and rebindable globals (R06-12)."""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

import pytest

from app.core.config import settings
from app.models.enums import EvaluationRunStatus
from app.workers import evaluation_tasks
from app.workers.celery_app import INCLUDE, celery_app
from app.workers.evaluation import facade
from app.workers.evaluation import tasks as evaluation_task_module

PACKAGE_DIR = Path(evaluation_tasks.__file__).resolve().parent / "evaluation"

# Names tests and callers import from, or rebind on, app.workers.evaluation_tasks.
CONTRACT_NAMES = (
    "SessionLocal",
    "LLMService",
    "QueryRetrievalService",
    "default_provider_factory",
    "_query_retrieval_service",
    "set_evaluation_status",
    "get_evaluation_status",
    "cleanup_eval_index_version_async",
    "_prepare_chunking_target_corpus_async",
    "_evaluate_question_pipeline_async",
    "_evaluate_with_llm_judge_async",
    "_run_evaluation_async",
    "_record_worker_audit",
    "_record_worker_audit_async",
    "_run",
    "ChunkingComparisonTarget",
    "ChunkingCorpusStats",
    "EvaluationRegressionThresholds",
    "EvaluationRunConfig",
    "EvaluationTask",
    "PermanentTaskError",
    "TransientTaskError",
    "_build_target_index_version",
    "_parse_run_config",
    "is_eval_index_version",
    "document_tasks",
    "run_evaluation",
)

_FACADE_ATTR = re.compile(r"\b(?:facade\(\)|f)\.([A-Za-z_][A-Za-z0-9_]*)")


@pytest.mark.parametrize("name", CONTRACT_NAMES)
def test_facade_keeps_every_contract_name(name: str) -> None:
    assert hasattr(evaluation_tasks, name), name


def test_rebindable_names_exist_and_are_exported() -> None:
    for name in evaluation_tasks.REBINDABLE_FACADE_NAMES:
        assert hasattr(evaluation_tasks, name), name
        assert name in evaluation_tasks.__all__, name
    assert facade() is evaluation_tasks


def test_modules_read_only_rebindable_names_from_the_facade() -> None:
    """Every ``facade().x`` / ``f.x`` in the package names a declared rebindable global."""
    seen: set[str] = set()
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        names = set(_FACADE_ATTR.findall(path.read_text(encoding="utf-8")))
        seen |= names
        unknown = names - set(evaluation_tasks.REBINDABLE_FACADE_NAMES)
        assert not unknown, (path.name, unknown)
    # Each rebindable name is actually read through the facade somewhere.
    assert set(evaluation_tasks.REBINDABLE_FACADE_NAMES) <= seen


def test_task_name_signature_and_route_are_unchanged() -> None:
    task = evaluation_tasks.run_evaluation
    assert task.name == "evaluations.run"
    assert celery_app.tasks["evaluations.run"].name == task.name
    assert list(inspect.signature(task.run).parameters) == [
        "evaluation_run_id",
        "request_id",
        "organization_id",
        "user_id",
        "force",
    ]
    route = celery_app.conf.task_routes["evaluations.run"]
    assert route["queue"] == settings.celery_queue_evaluations
    assert "app.workers.evaluation_tasks" in INCLUDE
    assert "app.workers.evaluation.tasks" in INCLUDE


def test_facade_and_modules_stay_under_500_lines() -> None:
    paths = [Path(evaluation_tasks.__file__), *sorted(PACKAGE_DIR.glob("*.py"))]
    for path in paths:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path.name


def test_parse_run_config_reads_metrics_service_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = object()

    class _Metrics:
        def parse_metric_options(self, raw: dict[str, Any]) -> object:
            return marker

    monkeypatch.setattr(evaluation_tasks, "_evaluation_metrics_service", _Metrics())
    config = evaluation_tasks._parse_run_config({"top_k": 2, "model_profile_id": " p1 "})
    assert config.metric_options is marker
    assert config.model_profile_id == "p1"


@pytest.mark.parametrize(
    "raw",
    [
        {"chunking_profile_id": 3},
        {"chunking_strategy": 1},
        {"profile_version": []},
        {"model_profile_id": 5},
        {"chunking_profile_config": "x"},
        {"selected_document_ids": "x"},
        {"selected_document_ids": [""]},
        {"selected_document_ids": ["not-a-uuid"]},
        {"metric_options": []},
        {"top_k": 0},
        {"rerank": "yes"},
        {"model_name": " "},
    ],
)
def test_parse_run_config_rejects_invalid_values(raw: dict[str, Any]) -> None:
    with pytest.raises(evaluation_tasks.PermanentTaskError, match="Invalid evaluation run"):
        evaluation_tasks._parse_run_config(raw)


def test_record_worker_audit_goes_through_facade_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake_async(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(evaluation_tasks, "_record_worker_audit_async", _fake_async)
    ran: list[object] = []

    def _fake_run(coro: Any) -> None:
        ran.append(coro)
        coro.close()

    monkeypatch.setattr(evaluation_tasks, "_run", _fake_run)
    evaluation_tasks._record_worker_audit(
        action="a",
        resource_type="evaluation_run",
        resource_id=None,
        organization_id=None,
        user_id=None,
        request_id=None,
    )
    assert len(ran) == 1


@pytest.mark.asyncio
async def test_record_worker_audit_async_skips_and_swallows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[int] = []

    class _Boom:
        def __call__(self) -> Any:
            opened.append(1)
            raise RuntimeError("db down")

    monkeypatch.setattr(evaluation_tasks, "SessionLocal", _Boom())
    kwargs: dict[str, Any] = {
        "action": "a",
        "resource_type": "evaluation_run",
        "resource_id": None,
        "user_id": None,
        "request_id": None,
    }
    await evaluation_tasks._record_worker_audit_async(organization_id=None, **kwargs)
    await evaluation_tasks._record_worker_audit_async(organization_id="bad", **kwargs)
    assert opened == []
    await evaluation_tasks._record_worker_audit_async(
        organization_id="00000000-0000-0000-0000-000000000001", **kwargs
    )
    assert opened == [1]


def test_terminal_failure_uses_facade_status_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses: list[EvaluationRunStatus] = []
    audits: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []

    def _set(run_id: str, *, status: EvaluationRunStatus, **_: Any) -> bool:
        statuses.append(status)
        return True

    monkeypatch.setattr(evaluation_tasks, "set_evaluation_status", _set)
    monkeypatch.setattr(evaluation_tasks, "_record_worker_audit", lambda **kw: audits.append(kw))
    from app.workers import notification_helper

    monkeypatch.setattr(notification_helper, "emit_notification", lambda **kw: notes.append(kw))
    task = evaluation_tasks.run_evaluation
    task.on_terminal_failure(exc=RuntimeError("x"), args=(), kwargs={})
    assert statuses == []
    task.on_terminal_failure(exc=RuntimeError("x"), args=("run-1",), kwargs={})
    assert statuses == [EvaluationRunStatus.failed]
    assert audits[0]["metadata"]["error_type"] == "RuntimeError"
    assert notes[0]["event_type"] == "evaluation_failed"

    def _raise(*_: Any, **__: Any) -> bool:
        raise RuntimeError("redis down")

    monkeypatch.setattr(evaluation_tasks, "set_evaluation_status", _raise)
    task.on_terminal_failure(exc=RuntimeError("x"), args=(), kwargs={"evaluation_run_id": "r"})


def test_run_evaluation_skips_completed_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evaluation_tasks, "get_evaluation_status", lambda _: EvaluationRunStatus.completed.value
    )
    assert evaluation_tasks.run_evaluation.run("run-1")["status"] == "skipped"

    monkeypatch.setattr(evaluation_tasks, "get_evaluation_status", lambda _: None)
    with pytest.raises(evaluation_tasks.PermanentTaskError, match="not found"):
        evaluation_tasks.run_evaluation.run("run-1")

    def _invalid(_: str) -> str:
        raise ValueError("bad id")

    monkeypatch.setattr(evaluation_tasks, "get_evaluation_status", _invalid)
    with pytest.raises(evaluation_tasks.PermanentTaskError, match="Invalid"):
        evaluation_tasks.run_evaluation.run("run-1")

    monkeypatch.setattr(
        evaluation_tasks, "get_evaluation_status", lambda _: EvaluationRunStatus.queued.value
    )
    monkeypatch.setattr(evaluation_tasks, "set_evaluation_status", lambda *a, **k: False)
    with pytest.raises(evaluation_tasks.TransientTaskError, match="running state"):
        evaluation_tasks.run_evaluation.run("run-1")


def test_run_evaluation_raises_when_final_state_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evaluation_tasks, "get_evaluation_status", lambda _: EvaluationRunStatus.queued.value
    )
    results = iter([True, False])
    monkeypatch.setattr(evaluation_tasks, "set_evaluation_status", lambda *a, **k: next(results))

    async def _summary(*_: Any, **__: Any) -> dict[str, Any]:
        return {
            "question_total_count": 1,
            "question_success_count": 1,
            "question_failure_count": 0,
            "all_questions_failed": False,
        }

    monkeypatch.setattr(evaluation_tasks, "_run_evaluation_async", _summary)
    with pytest.raises(evaluation_tasks.TransientTaskError, match="final state"):
        evaluation_tasks.run_evaluation.run("run-1")


def test_task_module_is_the_registered_implementation() -> None:
    assert evaluation_task_module.run_evaluation is evaluation_tasks.run_evaluation
    assert evaluation_task_module.EvaluationTask is evaluation_tasks.EvaluationTask
