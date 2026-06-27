from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from time import perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievalResult,
    GraphRetrievalService,
)
from app.domains.chat.services.keyword_retrieval_service import (
    KeywordRetrievalResult,
    KeywordRetrievalService,
)
from app.domains.chat.services.query_retrieval_service import (
    QdrantClientLike,
    QueryRetrievalService,
    RetrievedCandidate,
)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _estimate_cost_usd(token_count: int) -> Decimal:
    token_cost = Decimal(str(settings.openai_embedding_cost_per_million_tokens_usd))
    return (Decimal(max(token_count, 0)) / Decimal("1000000")) * token_cost


@dataclass(frozen=True)
class ParallelRetrievalBudget:
    max_parallel_calls: int = 4
    timeout_ms: int = 8_000
    max_retry_attempts: int = 1
    max_total_tokens: int | None = None
    max_total_cost_usd: Decimal | None = None


@dataclass(frozen=True)
class RetrievalBranchRecord:
    branch_name: str
    latency_ms: int
    succeeded: bool
    retries: int = 0
    candidate_count: int = 0
    error_code: str | None = None
    skipped: bool = False


@dataclass(frozen=True)
class RetrievalQueryRecord:
    query: str
    embedding_model: str | None
    embedding_prompt_tokens: int
    query_vector: list[float] | None
    vector_candidates: list[RetrievedCandidate] = field(default_factory=list)
    keyword_candidates: KeywordRetrievalResult | None = None
    branches: list[RetrievalBranchRecord] = field(default_factory=list)


@dataclass(frozen=True)
class ParallelRetrievalPlan:
    admitted_queries: list[str]
    max_parallel_calls: int
    timeout_ms: int
    max_retry_attempts: int
    max_total_tokens: int | None
    max_total_cost_usd: Decimal | None
    keyword_enabled: bool
    graph_enabled: bool


@dataclass(frozen=True)
class ParallelRetrievalResult:
    plan: ParallelRetrievalPlan
    query_records: list[RetrievalQueryRecord]
    graph_result: GraphRetrievalResult
    branch_records: list[RetrievalBranchRecord]
    total_embedding_prompt_tokens: int
    embedding_model: str | None


@dataclass(frozen=True)
class _CallOutcome:
    value: object | None
    record: RetrievalBranchRecord


class ParallelRetrievalOptimizer:
    """Runs safe retrieval branches in parallel with bounded fan-out.

    The optimizer keeps the existing org/document authorization semantics in the
    underlying services and only coordinates concurrency, timeouts, and retries.
    """

    @staticmethod
    def build_plan(
        *,
        queries: list[str],
        keyword_enabled: bool,
        graph_enabled: bool,
        budget: ParallelRetrievalBudget,
    ) -> ParallelRetrievalPlan:
        admitted_queries: list[str] = []
        token_total = 0
        cost_total = Decimal("0")

        for query in queries:
            query_tokens = _estimate_tokens(query)
            query_cost = _estimate_cost_usd(query_tokens)
            next_tokens = token_total + query_tokens
            next_cost = cost_total + query_cost
            if (
                budget.max_total_tokens is not None
                and admitted_queries
                and next_tokens > budget.max_total_tokens
            ):
                break
            if (
                budget.max_total_cost_usd is not None
                and admitted_queries
                and next_cost > budget.max_total_cost_usd
            ):
                break
            admitted_queries.append(query)
            token_total = next_tokens
            cost_total = next_cost

        if not admitted_queries and queries:
            admitted_queries = [queries[0]]

        return ParallelRetrievalPlan(
            admitted_queries=admitted_queries,
            max_parallel_calls=budget.max_parallel_calls,
            timeout_ms=budget.timeout_ms,
            max_retry_attempts=budget.max_retry_attempts,
            max_total_tokens=budget.max_total_tokens,
            max_total_cost_usd=budget.max_total_cost_usd,
            keyword_enabled=keyword_enabled,
            graph_enabled=graph_enabled,
        )

    async def execute(
        self,
        *,
        session: AsyncSession,
        organization_id: UUID,
        document_ids: list[UUID] | None,
        queries: list[str],
        query_retrieval_service: QueryRetrievalService,
        keyword_retrieval_service: KeywordRetrievalService,
        graph_retrieval_service: GraphRetrievalService,
        graph_enabled: bool,
        keyword_enabled: bool,
        qdrant_client: QdrantClientLike | None,
        top_k: int,
        exact_match_boost: float,
        budget: ParallelRetrievalBudget | None = None,
    ) -> ParallelRetrievalResult:
        if budget is None:
            budget = ParallelRetrievalBudget()

        plan = self.build_plan(
            queries=queries,
            keyword_enabled=keyword_enabled,
            graph_enabled=graph_enabled,
            budget=budget,
        )

        semaphore = asyncio.Semaphore(plan.max_parallel_calls)
        branch_records: list[RetrievalBranchRecord] = []

        graph_task = self._run_branch(
            branch_name="graph_expansion",
            semaphore=semaphore,
            timeout_ms=plan.timeout_ms,
            max_retry_attempts=plan.max_retry_attempts,
            factory=lambda: graph_retrieval_service.expand(
                session=session,
                organization_id=organization_id,
                question=queries[0] if queries else "",
                allowed_document_ids=document_ids,
                graph_enabled=graph_enabled,
            ),
        )

        async def _run_query(query: str) -> RetrievalQueryRecord:
            embed_outcome = await self._run_branch(
                branch_name="embedding",
                semaphore=semaphore,
                timeout_ms=plan.timeout_ms,
                max_retry_attempts=plan.max_retry_attempts,
                factory=lambda: query_retrieval_service.embed_query(question=query),
            )
            query_vector: list[float] | None = None
            embedding_prompt_tokens = 0
            embedding_model: str | None = None
            if embed_outcome.record.succeeded and isinstance(embed_outcome.value, tuple):
                query_vector = list(embed_outcome.value[0])
                embedding_prompt_tokens = int(embed_outcome.value[1])
                embedding_model = query_retrieval_service.embedding_model
            else:
                return RetrievalQueryRecord(
                    query=query,
                    embedding_model=embedding_model,
                    embedding_prompt_tokens=0,
                    query_vector=None,
                    vector_candidates=[],
                    keyword_candidates=None,
                    branches=[embed_outcome.record],
                )

            vector_task = self._run_branch(
                branch_name="vector_search",
                semaphore=semaphore,
                timeout_ms=plan.timeout_ms,
                max_retry_attempts=plan.max_retry_attempts,
                factory=lambda: asyncio.to_thread(
                    query_retrieval_service.retrieve_candidates,
                    query_vector=query_vector,
                    organization_id=organization_id,
                    document_ids=document_ids,
                    initial_top_k=top_k,
                    qdrant_client=qdrant_client,
                ),
            )
            if plan.keyword_enabled:
                keyword_task = self._run_branch(
                    branch_name="keyword_search",
                    semaphore=semaphore,
                    timeout_ms=plan.timeout_ms,
                    max_retry_attempts=plan.max_retry_attempts,
                    factory=lambda: keyword_retrieval_service.search_chunks(
                        session=session,
                        query=query,
                        organization_id=organization_id,
                        document_ids=document_ids,
                        top_k=top_k,
                        exact_match_boost=exact_match_boost,
                    ),
                )
                vector_outcome, keyword_outcome = await asyncio.gather(vector_task, keyword_task)
            else:
                vector_outcome = await vector_task
                keyword_outcome = _CallOutcome(
                    value=None,
                    record=RetrievalBranchRecord(
                        branch_name="keyword_search",
                        latency_ms=0,
                        succeeded=True,
                        skipped=True,
                    ),
                )
            vector_candidates = (
                list(vector_outcome.value)
                if vector_outcome.record.succeeded and isinstance(vector_outcome.value, list)
                else []
            )
            keyword_result = (
                keyword_outcome.value
                if keyword_outcome.record.succeeded
                and isinstance(keyword_outcome.value, KeywordRetrievalResult)
                else None
            )
            return RetrievalQueryRecord(
                query=query,
                embedding_model=embedding_model,
                embedding_prompt_tokens=embedding_prompt_tokens,
                query_vector=query_vector,
                vector_candidates=vector_candidates,
                keyword_candidates=keyword_result,
                branches=[embed_outcome.record, vector_outcome.record, keyword_outcome.record],
            )

        query_tasks = [_run_query(query) for query in plan.admitted_queries]
        query_records = await asyncio.gather(*query_tasks) if query_tasks else []
        graph_outcome = await graph_task
        if graph_outcome.record.succeeded and isinstance(graph_outcome.value, GraphRetrievalResult):
            graph_result = graph_outcome.value
        else:
            graph_result = GraphRetrievalResult(
                graph_context_enabled=graph_enabled,
                graph_context_used=False,
                graph_context_unavailable=False,
                graph_context_reason=graph_outcome.record.error_code or "graph_unavailable",
            )

        for record in query_records:
            branch_records.extend(record.branches)
        branch_records.append(graph_outcome.record)
        total_embedding_prompt_tokens = sum(
            record.embedding_prompt_tokens for record in query_records
        )
        embedding_model = next(
            (
                record.embedding_model
                for record in query_records
                if record.embedding_model is not None
            ),
            None,
        )
        return ParallelRetrievalResult(
            plan=plan,
            query_records=query_records,
            graph_result=graph_result,
            branch_records=branch_records,
            total_embedding_prompt_tokens=total_embedding_prompt_tokens,
            embedding_model=embedding_model,
        )

    async def _run_branch(
        self,
        *,
        branch_name: str,
        semaphore: asyncio.Semaphore,
        timeout_ms: int,
        max_retry_attempts: int,
        factory: Callable[[], Awaitable[object]],
    ) -> _CallOutcome:
        attempts = 0
        last_error_code: str | None = None
        while True:
            started = perf_counter()
            try:
                async with semaphore:
                    value = await asyncio.wait_for(factory(), timeout=timeout_ms / 1000)
                latency_ms = int((perf_counter() - started) * 1000)
                record = RetrievalBranchRecord(
                    branch_name=branch_name,
                    latency_ms=latency_ms,
                    succeeded=True,
                    retries=attempts,
                    candidate_count=self._candidate_count(value),
                )
                return _CallOutcome(value=value, record=record)
            except TimeoutError:
                last_error_code = "timeout"
            except Exception as exc:  # pragma: no cover - defensive fallback
                last_error_code = exc.__class__.__name__

            attempts += 1
            latency_ms = int((perf_counter() - started) * 1000)
            if attempts > max_retry_attempts:
                record = RetrievalBranchRecord(
                    branch_name=branch_name,
                    latency_ms=latency_ms,
                    succeeded=False,
                    retries=max(0, attempts - 1),
                    error_code=last_error_code,
                )
                return _CallOutcome(value=None, record=record)

    @staticmethod
    def _candidate_count(value: object | None) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, GraphRetrievalResult):
            return len(value.chunks)
        if isinstance(value, KeywordRetrievalResult):
            return len(value.candidates)
        return 0
