"""R02-06: each concurrent keyword branch uses its own DB session; failures are reported."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from uuid import uuid4

import pytest

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
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.domains.chat.services import parallel_retrieval_optimizer as optimizer_module
from app.domains.chat.services.graph_retrieval_service import GraphRetrievalResult
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalResult
from app.domains.chat.services.parallel_retrieval_optimizer import (
    ParallelRetrievalBudget,
    ParallelRetrievalOptimizer,
)


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.closed = True


class _Factory:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> Any:
        session = _FakeSession()
        self.sessions.append(session)
        return session


class _Query:
    embedding_model = "test-embedding"

    async def embed_query(self, *, question: str) -> tuple[list[float], int]:
        return [1.0], 1

    def retrieve_candidates(self, **kwargs: object) -> list[object]:
        return []


class _Graph:
    async def expand(self, **kwargs: object) -> GraphRetrievalResult:
        return GraphRetrievalResult(
            graph_context_enabled=False, graph_context_used=False, graph_context_reason="disabled"
        )


class _Keyword:
    def __init__(self, *, fail_first: int = 0, error: Exception | None = None, delay: float = 0):
        self.sessions: list[object] = []
        self.fail_first = fail_first
        self.error = error
        self.delay = delay

    async def search_chunks(self, *, session: object, query: str, **kwargs: object) -> Any:
        self.sessions.append(session)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None and (
            self.fail_first == 0 or len(self.sessions) <= self.fail_first
        ):
            raise self.error
        return KeywordRetrievalResult(candidates=[], query_tokens=[query], exact_match_tokens=[])


async def _run(
    optimizer: ParallelRetrievalOptimizer,
    keyword: _Keyword,
    caller_session: object,
    *,
    queries: list[str],
    keyword_enabled: bool = True,
    budget: ParallelRetrievalBudget | None = None,
) -> Any:
    return await optimizer.execute(
        session=caller_session,  # type: ignore[arg-type]
        organization_id=uuid4(),
        document_ids=None,
        queries=queries,
        query_retrieval_service=_Query(),  # type: ignore[arg-type]
        keyword_retrieval_service=keyword,  # type: ignore[arg-type]
        graph_retrieval_service=_Graph(),  # type: ignore[arg-type]
        graph_enabled=False,
        keyword_enabled=keyword_enabled,
        qdrant_client=None,
        top_k=3,
        exact_match_boost=1.5,
        budget=budget
        or ParallelRetrievalBudget(max_parallel_calls=4, timeout_ms=1000, max_retry_attempts=0),
    )


@pytest.fixture
def reports(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    captured: dict[str, list[Any]] = {"metric": [], "log": []}
    monkeypatch.setattr(
        optimizer_module,
        "record_retrieval_branch_failure",
        lambda branch, error: captured["metric"].append((branch, error)),
    )

    class _Log:
        def warning(self, event: str, **kw: object) -> None:
            captured["log"].append((event, kw))

    monkeypatch.setattr(optimizer_module, "logger", _Log())
    return captured


@pytest.mark.asyncio
async def test_three_queries_use_three_distinct_closed_sessions() -> None:
    factory = _Factory()
    keyword = _Keyword(delay=0.02)
    caller = object()

    await _run(
        ParallelRetrievalOptimizer(session_factory=factory),
        keyword,
        caller,
        queries=["a", "b", "c"],
    )

    assert len(keyword.sessions) == 3
    assert len({id(s) for s in keyword.sessions}) == 3
    assert all(s is not caller for s in keyword.sessions)
    assert len(factory.sessions) == 3
    assert all(s.closed for s in factory.sessions)


@pytest.mark.asyncio
async def test_single_query_reuses_caller_session() -> None:
    factory = _Factory()
    keyword = _Keyword()
    caller = object()

    await _run(ParallelRetrievalOptimizer(session_factory=factory), keyword, caller, queries=["a"])

    assert factory.sessions == []
    assert keyword.sessions == [caller]


@pytest.mark.asyncio
async def test_keyword_disabled_does_not_open_sessions() -> None:
    factory = _Factory()
    keyword = _Keyword()

    await _run(
        ParallelRetrievalOptimizer(session_factory=factory),
        keyword,
        object(),
        queries=["a", "b"],
        keyword_enabled=False,
    )

    assert factory.sessions == []
    assert keyword.sessions == []


@pytest.mark.asyncio
async def test_keyword_failure_is_logged_and_counted(reports: dict[str, list[Any]]) -> None:
    keyword = _Keyword(error=RuntimeError("SELECT secret question text"))

    result = await _run(
        ParallelRetrievalOptimizer(session_factory=_Factory()),
        keyword,
        object(),
        queries=["a", "b"],
    )

    failed = [r for r in result.branch_records if r.branch_name == "keyword_search"]
    assert len(failed) == 2
    assert all(not r.succeeded and r.error_code == "RuntimeError" for r in failed)
    assert reports["metric"] == [("keyword_search", "RuntimeError")] * 2
    event, fields = reports["log"][0]
    assert event == "retrieval.branch.failed"
    assert fields["branch"] == "keyword_search"
    assert fields["error_code"] == "RuntimeError"
    assert "secret" not in str(fields)


@pytest.mark.asyncio
async def test_timeout_reports_timeout_error(reports: dict[str, list[Any]]) -> None:
    keyword = _Keyword(delay=0.5)

    result = await _run(
        ParallelRetrievalOptimizer(session_factory=_Factory()),
        keyword,
        object(),
        queries=["a", "b"],
        budget=ParallelRetrievalBudget(max_parallel_calls=4, timeout_ms=20, max_retry_attempts=0),
    )

    records = [r for r in result.branch_records if r.branch_name == "keyword_search"]
    assert len(records) == 2
    assert all(not r.succeeded and r.error_code == "timeout" for r in records)
    assert ("keyword_search", "timeout") in reports["metric"]


@pytest.mark.asyncio
async def test_each_retry_attempt_gets_fresh_session(reports: dict[str, list[Any]]) -> None:
    factory = _Factory()
    keyword = _Keyword(fail_first=1, error=RuntimeError("boom"))

    # Two queries so branch sessions are used; the first search call fails once.
    result = await _run(
        ParallelRetrievalOptimizer(session_factory=factory),
        keyword,
        object(),
        queries=["a", "b"],
        budget=ParallelRetrievalBudget(max_parallel_calls=4, timeout_ms=1000, max_retry_attempts=1),
    )

    # 2 branches + 1 retry of the failed one = 3 sessions, all distinct and closed.
    assert len(factory.sessions) == 3
    assert all(s.closed for s in factory.sessions)
    assert len({id(s) for s in keyword.sessions}) == 3
    assert all(r.succeeded for r in result.branch_records if r.branch_name == "keyword_search")
    assert reports["metric"] == [("keyword_search", "RuntimeError")]
