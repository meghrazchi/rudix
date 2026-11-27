"""Branches of the split evaluation run that the worker suites do not reach (R06-12).

Collaborators are rebound on the ``evaluation_tasks`` facade; no database is used.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.domains.chat.services.llm_service import TransientLLMServiceError
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate
from app.domains.evaluations.services.evaluation_metrics_service import EvaluationMetricOptions
from app.workers import evaluation_tasks
from app.workers.base_task import PermanentTaskError, TransientTaskError
from app.workers.evaluation import comparison, config, corpus, question
from app.workers.evaluation import run as run_module

ORG = uuid4()
OTHER_ORG = uuid4()
DOC = uuid4()


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@dataclass
class _Question:
    question: str
    id: UUID = field(default_factory=uuid4)
    expected_answer: str | None = "Twenty days."
    expected_document_id: UUID | None = DOC
    expected_page_number: int | None = 1
    metadata_json: dict[str, Any] | None = None


@dataclass
class _Repo:
    run: Any
    evaluation_set: Any
    questions: list[_Question]
    fail_delete: bool = False
    summary_row: Any = True
    fail_summary: bool = False
    results: list[dict[str, Any]] = field(default_factory=list)

    async def get_evaluation_run(self, session: Any, **_: Any) -> Any:
        return self.run

    async def get_evaluation_set_by_id(self, session: Any, **_: Any) -> Any:
        return self.evaluation_set

    async def list_all_evaluation_questions(self, session: Any, **_: Any) -> list[_Question]:
        return self.questions

    async def delete_evaluation_results_for_run(self, session: Any, **_: Any) -> int:
        if self.fail_delete:
            raise RuntimeError("db down")
        return 0

    async def create_evaluation_result(self, session: Any, **kwargs: Any) -> None:
        self.results.append(kwargs)

    async def update_evaluation_run_config(self, session: Any, **_: Any) -> Any:
        if self.fail_summary:
            raise RuntimeError("db down")
        return self.summary_row


class _Docs:
    async def get_document_by_id(self, session: Any, *, document_id: UUID) -> Any:
        org = ORG if document_id == DOC else OTHER_ORG
        return type(
            "Doc",
            (),
            {
                "organization_id": org,
                "file_type": "pdf",
                "language": "en",
                "chunking_config_snapshot": {"ocr_applied": False},
            },
        )()

    async def list_document_chunks(self, session: Any, **_: Any) -> list[Any]:
        return [type("C", (), {"token_count": 10})()]


class _Retrieval:
    embedding_model = "fake"

    async def embed_query(self, **_: Any) -> tuple[list[float], int]:
        return [0.1], 1

    def retrieve_candidates(self, **_: Any) -> list[RetrievedCandidate]:
        return [
            RetrievedCandidate(
                document_id=DOC,
                chunk_id=UUID(int=1),
                filename="p.pdf",
                page_number=1,
                text="Employees receive twenty days of leave.",
                similarity_score=0.95,
            )
        ]


class _LLM:
    def __init__(self, *, model_name: str | None = None) -> None:
        self.model_name = model_name or "m"

    async def generate_answer(self, *, prompt: str, **_: Any) -> object:
        if "Fails" in prompt:
            raise TransientLLMServiceError("provider down")
        not_found = "Unknown" in prompt
        return type(
            "R",
            (),
            {
                "answer": "" if not_found else "Employees receive twenty days of leave.",
                "not_found": not_found,
                "citations": [],
                "model_name": self.model_name,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "approximate_cost_usd": Decimal("0"),
                "latency_ms": 1,
            },
        )()


def _wire(monkeypatch: pytest.MonkeyPatch, repo: _Repo, **overrides: Any) -> None:
    monkeypatch.setattr(evaluation_tasks, "SessionLocal", _Session)
    monkeypatch.setattr(evaluation_tasks, "_evaluation_repository", repo)
    monkeypatch.setattr(evaluation_tasks, "_document_repository", _Docs())
    monkeypatch.setattr(evaluation_tasks, "_query_retrieval_service", _Retrieval())
    monkeypatch.setattr(evaluation_tasks, "LLMService", _LLM)

    async def _no_profile(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(run_module, "resolve_task_profile", _no_profile)

    async def _judge(**_: Any) -> Any:
        raise RuntimeError("judge down")

    monkeypatch.setattr(evaluation_tasks, "_evaluate_with_llm_judge_async", _judge)

    async def _cleanup(**kwargs: Any) -> Any:
        return type("R", (), {"as_dict": lambda self: {"index_version": "x"}})()

    monkeypatch.setattr(evaluation_tasks, "cleanup_eval_index_version_async", _cleanup)
    for name, value in overrides.items():
        monkeypatch.setattr(evaluation_tasks, name, value)


def _repo(**kwargs: Any) -> _Repo:
    run = type(
        "Run",
        (),
        {
            "evaluation_set_id": uuid4(),
            "prompt_template_version_id": kwargs.pop("template_id", None),
            "config": kwargs.pop(
                "config",
                {
                    "rerank": False,
                    "selected_document_ids": [str(DOC), str(uuid4())],
                    "metric_options": {"faithfulness": True},
                },
            ),
        },
    )()
    evaluation_set = type("Set", (), {"id": uuid4(), "organization_id": ORG})()
    questions = [
        _Question("Fails: how much leave?"),
        _Question("Unknown: how much leave?", metadata_json={"use_case": "hr"}),
        _Question("Works: how much leave?", metadata_json={"tags": ["", "policy"]}),
    ]
    return _Repo(run=run, evaluation_set=evaluation_set, questions=questions, **kwargs)


@pytest.mark.asyncio
async def test_run_with_prompt_template_and_question_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(template_id=uuid4())

    class _Templates:
        async def get_version_by_id(self, session: Any, **_: Any) -> Any:
            return type("V", (), {"id": uuid4(), "version_number": 3, "content": None})()

    _wire(monkeypatch, repo, _prompt_template_repository=_Templates())
    result = await evaluation_tasks._run_evaluation_async(str(uuid4()))

    assert result["question_failure_count"] == 1  # the LLM error
    assert [r["details"]["status"] for r in repo.results] == ["failed", "completed", "completed"]
    assert repo.results[0]["details"]["error"] == "llm_generation_failed"
    assert repo.results[1]["details"]["not_found"] is True
    assert repo.results[2]["details"]["metrics"]["judge_error"] == "RuntimeError"
    assert repo.results[2]["details"]["prompt_template"]["version_number"] == 3
    assert result["metrics_summary"]["prompt_template"]["version_number"] == 3
    assert set(result["metrics_summary"]["best_by_use_case"]) == {"unlabeled", "hr", "policy"}


@pytest.mark.asyncio
async def test_prompt_template_from_config_and_missing_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(template_id=uuid4(), config={"prompt_template": {"name": "t"}})

    class _Templates:
        version: Any = type("V", (), {"id": uuid4(), "version_number": 1, "content": "{q}"})()

        async def get_version_by_id(self, session: Any, **_: Any) -> Any:
            return self.version

    templates = _Templates()
    _wire(monkeypatch, repo, _prompt_template_repository=templates)
    run = repo.run
    assert await run_module._load_prompt_template(_Session(), run) == ("{q}", {"name": "t"})  # type: ignore[arg-type]
    templates.version = None
    assert await run_module._load_prompt_template(_Session(), run) == (None, None)


@pytest.mark.asyncio
async def test_model_profile_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    def cfg(profile_id: str) -> Any:
        return config._parse_run_config({"model_profile_id": profile_id})

    with pytest.raises(PermanentTaskError, match="Invalid model_profile_id"):
        await run_module._resolve_profile(_Session(), cfg("nope"), ORG)  # type: ignore[arg-type]

    found: list[Any] = [None]

    async def _get(*_: Any, **__: Any) -> Any:
        return found[0]

    monkeypatch.setattr(run_module, "get_profile_by_id", _get)
    monkeypatch.setattr(run_module, "_profile_to_resolved", lambda row: ("resolved", row))
    with pytest.raises(PermanentTaskError, match="not found or inaccessible"):
        await run_module._resolve_profile(_Session(), cfg(str(uuid4())), ORG)  # type: ignore[arg-type]
    found[0] = "row"
    resolved = await run_module._resolve_profile(_Session(), cfg(str(uuid4())), ORG)  # type: ignore[arg-type]
    assert resolved == ("resolved", "row")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "error", "match"),
    [
        ({"run": None}, PermanentTaskError, "Evaluation run not found"),
        ({"evaluation_set": None}, PermanentTaskError, "Evaluation set not found"),
        ({"fail_delete": True}, TransientTaskError, "clear stale"),
        ({"summary_row": None}, TransientTaskError, "persist evaluation summary"),
        ({"fail_summary": True}, TransientTaskError, "persist evaluation summary"),
    ],
)
async def test_run_error_paths(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, Any], error: type, match: str
) -> None:
    repo = _repo()
    for key, value in change.items():
        setattr(repo, key, value)
    _wire(monkeypatch, repo)
    with pytest.raises(error, match=match):
        await evaluation_tasks._run_evaluation_async(str(uuid4()))


@pytest.mark.asyncio
async def test_invalid_run_id_is_permanent() -> None:
    with pytest.raises(PermanentTaskError, match="Invalid evaluation_run_id"):
        await evaluation_tasks._run_evaluation_async("not-a-uuid")


@pytest.mark.asyncio
async def test_rerank_skips_unknown_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domains.chat.services.rerank_service import RerankedCandidate

    class _Rerank:
        async def rerank(self, **_: Any) -> Any:
            ghost = RerankedCandidate(
                key="ghost",
                similarity_score=0.1,
                original_rank=1,
                rerank_score=None,
                rerank_rank=None,
                final_rank=1,
            )
            return type("RR", (), {"candidates": [ghost]})()

    monkeypatch.setattr(evaluation_tasks, "_rerank_service", _Rerank())
    chunk = question.RetrievedChunk(
        document_id=DOC,
        chunk_id=uuid4(),
        filename="p",
        page_number=1,
        text="t",
        similarity_score=0.5,
    )
    selected, _ = await question._rerank_chunks(
        query="q", chunks=[chunk], enabled=True, final_top_k=1
    )
    assert selected == []


def test_config_helpers() -> None:
    assert config._normalize_score(" 0.25 ") == 0.25
    assert config._normalize_score("abc") is None
    assert config._normalize_score(None) is None
    assert config._parse_comparison_targets("x") == []
    assert [t.label for t in config._parse_comparison_targets(["x", {}])] == ["Target 2"]
    doc = str(uuid4())
    assert config._parse_selected_document_ids([doc, doc]) == [UUID(doc)]
    pinned = config._parse_run_config({"chunking_profile_id": "p1", "run_name": "Pinned"})
    targets = config.resolve_comparison_targets(pinned)
    assert [(t.label, t.profile_source) for t in targets] == [("Pinned", "organization_profile")]
    inline = config._parse_run_config({"chunking_profile_config": {"strategy": "x"}})
    assert config.resolve_comparison_targets(inline)[0].profile_source == "inline_profile"
    assert isinstance(pinned.metric_options, EvaluationMetricOptions)


def test_comparison_helpers() -> None:
    thresholds = config.EvaluationRegressionThresholds(max_not_found_rate=0.1)
    flags = comparison._build_regression_flags(
        baseline_summary=None, candidate_summary={"not_found_rate": 0.5}, thresholds=thresholds
    )
    assert [flag["metric"] for flag in flags] == ["not_found_rate"]
    assert comparison._question_use_case(_Question("q", metadata_json={"tags": ["", 3]})) == (
        "unlabeled"
    )
    best_type, _ = comparison._build_best_target_by_dimension(
        documents_by_id={},
        questions=[_Question("q", expected_document_id=None)],  # type: ignore[list-item]
        per_target_question_scores={"A": {}},
    )
    assert best_type == {}
    assert comparison._summarize_dimension(defaultdict(list)) == {}


@pytest.mark.asyncio
async def test_corpus_stats_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluation_tasks, "_document_repository", _Docs())
    stats = await corpus._collect_chunking_corpus_stats_async(
        session=_Session(),  # type: ignore[arg-type]
        document_ids=[DOC],
        index_version="v1",
    )
    assert stats.ocr_breakdown == {"native_text": 1}
    assert corpus._ocr_bucket({"ocr_applied": True}) == "ocr_applied"
    assert corpus._ocr_bucket(None) == "unknown"
