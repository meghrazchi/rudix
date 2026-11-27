"""Bounded per-question concurrency of evaluation runs (R06-12).

``EVALUATION_MAX_CONCURRENT_QUESTIONS`` bounds the questions of one target in flight;
results are written in question order, each in its own short session, and a bound of 3
produces the same results as 1. Runs on SQLite, and on PostgreSQL (separate connections
per session) when TEST_DATABASE_URL is set.
"""

from __future__ import annotations

import asyncio
import threading
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from sqlalchemy import select

from app.core import metrics_workers
from app.core.config import settings
from app.db.tenant_context import tenant_context_scope
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.evaluations.services.evaluation_metrics_service import EvaluationJudgeScores
from app.models.enums import EvaluationRunStatus
from app.models.evaluation import EvaluationResult
from app.workers import evaluation_tasks
from app.workers.base_task import TransientTaskError
from app.workers.evaluation import target as target_module

QUESTIONS = [f"Question {n}: how many leave days apply in case {n}?" for n in range(6)]
VOLATILE_DETAIL_KEYS = {"latencies_ms"}


class Tracker:
    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0
        self.retrieve_threads: set[str] = set()
        self.judge_calls = 0

    def enter(self) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)

    def leave(self) -> None:
        self.in_flight -= 1


class FakeRetrieval:
    """Deterministic per question; later questions answer faster, so they finish first."""

    embedding_model = "fake-embedding"

    def __init__(self, tracker: Tracker, document_id: UUID) -> None:
        self.tracker = tracker
        self.document_id = document_id
        self._question_by_vector: dict[float, int] = {}

    async def embed_query(self, *, question: str, **_: Any) -> tuple[list[float], int]:
        position = int(question.split(":")[0].split()[-1])
        await asyncio.sleep(0.002 * (len(QUESTIONS) - position))
        return [float(position)] * 4, 3

    def retrieve_candidates(self, *, query_vector: list[float], **_: Any) -> list[Any]:
        self.tracker.retrieve_threads.add(threading.current_thread().name)
        position = int(query_vector[0])
        if position == 4:
            raise RuntimeError("qdrant timeout")
        return [
            RetrievedCandidate(
                document_id=self.document_id,
                chunk_id=UUID(int=position + 1),
                filename="policy.txt",
                page_number=1,
                text=f"Case {position}: employees receive {20 + position} days of leave.",
                similarity_score=0.9 - position * 0.01,
            )
        ]


class FakeLLM:
    def __init__(self, *, model_name: str | None = None) -> None:
        self.model_name = model_name or "fake-llm"

    async def generate_answer(self, *, prompt: str, **_: Any) -> object:
        await asyncio.sleep(0.001)
        days = prompt.split("employees receive ")[1].split(" ")[0]
        return type(
            "R",
            (),
            {
                "answer": f"Employees receive {days} days of leave.",
                "not_found": False,
                "citations": [],
                "model_name": self.model_name,
                "prompt_tokens": 7,
                "completion_tokens": 5,
                "total_tokens": 12,
                "approximate_cost_usd": Decimal("0.00001"),
                "latency_ms": 2,
                "retry_count": 0,
                "used_fallback_parser": False,
            },
        )()


def _seed_run(env: IngestionEnv) -> tuple[str, UUID, UUID]:
    seeded = env.seed(status="indexed")
    return env.run_async(_seed_evaluation(env, seeded))


async def _seed_evaluation(env: IngestionEnv, seeded: Any) -> tuple[str, UUID, UUID]:
    repository = EvaluationRepository()
    async with env.factory() as session:
        evaluation_set = await repository.create_evaluation_set(
            session, organization_id=seeded.organization_id, name="Concurrency set"
        )
        for text in QUESTIONS:
            await repository.create_evaluation_question(
                session,
                evaluation_set_id=evaluation_set.id,
                question=text,
                expected_answer="Employees receive leave.",
                expected_document_id=seeded.document_id,
                expected_page_number=1,
            )
        run = await repository.create_evaluation_run(
            session,
            evaluation_set_id=evaluation_set.id,
            status=EvaluationRunStatus.queued.value,
            config={
                "top_k": 3,
                "rerank": False,
                "selected_document_ids": [str(seeded.document_id)],
                "metric_options": {"faithfulness": True},
            },
        )
        await session.commit()
        return str(run.id), seeded.organization_id, seeded.document_id


class Wiring:
    def __init__(self, env: IngestionEnv, document_id: UUID) -> None:
        self.tracker = Tracker()
        self.write_order: list[UUID] = []
        self.write_sessions: list[Any] = []
        self.gauge: list[int] = [0]
        self.fail_on_write: int | None = None
        mp = env.monkeypatch
        mp.setattr(evaluation_tasks, "SessionLocal", env.factory)
        mp.setattr(evaluation_tasks, "LLMService", FakeLLM)
        mp.setattr(
            evaluation_tasks, "_query_retrieval_service", FakeRetrieval(self.tracker, document_id)
        )

        pipeline = evaluation_tasks._evaluate_question_pipeline_async

        async def _tracked_pipeline(**kwargs: Any) -> Any:
            self.tracker.enter()
            try:
                return await pipeline(**kwargs)
            finally:
                self.tracker.leave()

        mp.setattr(evaluation_tasks, "_evaluate_question_pipeline_async", _tracked_pipeline)

        async def _judge(**_: Any) -> EvaluationJudgeScores:
            await asyncio.sleep(0.001)
            # The judge runs inside the bound: its question is still counted in flight.
            assert 1 <= self.tracker.in_flight <= settings.evaluation_max_concurrent_questions
            self.tracker.judge_calls += 1
            return EvaluationJudgeScores(
                faithfulness_score=0.8, answer_relevance_score=0.7, provider="fake"
            )

        mp.setattr(evaluation_tasks, "_evaluate_with_llm_judge_async", _judge)
        repository = EvaluationRepository()
        original = repository.create_evaluation_result

        async def _create(session: Any, **kwargs: Any) -> Any:
            if self.fail_on_write is not None and len(self.write_order) == self.fail_on_write:
                raise RuntimeError("db down")
            self.write_order.append(kwargs["evaluation_question_id"])
            self.write_sessions.append(session)  # kept alive: ids stay unique
            return await original(session, **kwargs)

        repository.create_evaluation_result = _create  # type: ignore[method-assign]
        mp.setattr(evaluation_tasks, "_evaluation_repository", repository)

        def _gauge(delta: int) -> None:
            self.gauge.append(self.gauge[-1] + delta)

        mp.setattr(target_module, "record_evaluation_question_in_flight", _gauge)


def _run(env: IngestionEnv, run_id: str, org_id: UUID, bound: int) -> dict[str, Any]:
    env.monkeypatch.setattr(settings, "evaluation_max_concurrent_questions", bound)
    with tenant_context_scope(org_id):
        return env.run_async(evaluation_tasks._run_evaluation_async(run_id))


async def _rows(env: IngestionEnv, run_id: str) -> dict[UUID, EvaluationResult]:
    async with env.factory() as session:
        rows = await session.execute(
            select(EvaluationResult).where(EvaluationResult.evaluation_run_id == UUID(run_id))
        )
        return {row.evaluation_question_id: row for row in rows.scalars()}


def _comparable(row: EvaluationResult) -> dict[str, Any]:
    details = {k: v for k, v in row.details.items() if k not in VOLATILE_DETAIL_KEYS}
    details.pop("metrics", None)
    return {
        "answer": row.generated_answer,
        "retrieval_score": row.retrieval_score,
        "faithfulness": row.faithfulness_score,
        "relevance": row.answer_relevance_score,
        "details": details,
    }


async def _question_ids(env: IngestionEnv, run_id: str) -> list[UUID]:
    from app.models.evaluation import EvaluationQuestion, EvaluationRun

    async with env.factory() as session:
        run = (
            await session.execute(select(EvaluationRun).where(EvaluationRun.id == UUID(run_id)))
        ).scalar_one()
        rows = await EvaluationRepository().list_all_evaluation_questions(
            session, evaluation_set_id=run.evaluation_set_id
        )
        assert all(isinstance(row, EvaluationQuestion) for row in rows)
        return [row.id for row in rows]


def _scenario(env: IngestionEnv) -> None:
    run_id, org_id, document_id = _seed_run(env)
    question_ids = env.run_async(_question_ids(env, run_id))
    outcomes: dict[int, tuple[dict[str, Any], dict[UUID, dict[str, Any]], Wiring]] = {}
    for bound in (1, 3):
        wiring = Wiring(env, document_id)
        result = _run(env, run_id, org_id, bound)
        rows = env.run_async(_rows(env, run_id))
        outcomes[bound] = (result, {qid: _comparable(row) for qid, row in rows.items()}, wiring)

        assert wiring.write_order == question_ids  # question order, whatever finished first
        assert len({id(s) for s in wiring.write_sessions}) == len(
            QUESTIONS
        )  # one short session each
        assert wiring.tracker.max_in_flight == bound
        assert wiring.tracker.judge_calls == len(QUESTIONS) - 1
        assert max(wiring.gauge) == bound and wiring.gauge[-1] == 0
        main = threading.main_thread().name
        if bound == 1:
            assert wiring.tracker.retrieve_threads == {main}
        else:
            assert main not in wiring.tracker.retrieve_threads

    sequential, concurrent = outcomes[1], outcomes[3]
    assert sequential[1] == concurrent[1]
    for key in ("question_total_count", "question_success_count", "question_failure_count"):
        assert sequential[0][key] == concurrent[0][key]
    assert sequential[0]["question_failure_count"] == 1
    summary_keys = ("retrieval_hit_rate", "faithfulness_score", "not_found_rate")
    for key in summary_keys:
        assert sequential[0]["metrics_summary"].get(key) == concurrent[0]["metrics_summary"].get(
            key
        )


def test_concurrency_three_matches_sequential(ingestion_env: IngestionEnv) -> None:  # noqa: F811
    _scenario(ingestion_env)


@pytest.mark.requires_postgres
def test_concurrency_three_matches_sequential_pg(
    ingestion_env_pg: IngestionEnv,  # noqa: F811
) -> None:
    _scenario(ingestion_env_pg)


def test_persist_failure_stops_the_run_and_cancels_the_rest(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    run_id, org_id, document_id = _seed_run(env)
    wiring = Wiring(env, document_id)
    wiring.fail_on_write = 2
    with pytest.raises(TransientTaskError, match="persist evaluation result"):
        _run(env, run_id, org_id, 3)
    assert len(wiring.write_order) == 2
    assert wiring.gauge[-1] == 0
    assert len(env.run_async(_rows(env, run_id))) == 2


def test_in_flight_gauge_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    gauge = metrics_workers.EVALUATION_QUESTIONS_IN_FLIGHT
    monkeypatch.setattr(metrics_workers, "is_metrics_enabled", lambda: True)
    before = gauge._value.get()
    metrics_workers.record_evaluation_question_in_flight(1)
    assert gauge._value.get() == before + 1
    metrics_workers.record_evaluation_question_in_flight(-1)
    assert gauge._value.get() == before

    def _boom(_: int) -> None:
        raise RuntimeError("registry")

    monkeypatch.setattr(gauge, "inc", _boom)
    metrics_workers.record_evaluation_question_in_flight(1)  # swallowed
    monkeypatch.setattr(metrics_workers, "is_metrics_enabled", lambda: False)
    metrics_workers.record_evaluation_question_in_flight(1)
    assert gauge._value.get() == before


def test_concurrency_setting_bounds() -> None:
    from pydantic import ValidationError

    from app.core.settings.workers import WorkersSettings

    assert WorkersSettings().evaluation_max_concurrent_questions == 1
    for bad in (0, 33):
        with pytest.raises(ValidationError):
            WorkersSettings(evaluation_max_concurrent_questions=bad)
