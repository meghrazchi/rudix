from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from decimal import Decimal

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

from app.core.config import settings
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.domains.chat.schemas.chat import ChatCitationResponse
from app.domains.chat.services.citation_service import CitationContextChunk
from app.domains.chat.services.confidence_service import ConfidenceChunkSignal
from app.domains.chat.services.llm_service import LLMAnswerResult, LLMService
from app.domains.chat.services.prompt_service import PromptService
from app.domains.chat.services.tree_search_service import (
    TreeSearchCandidateDraft,
    TreeSearchService,
)


@dataclass
class _FakeResponse:
    content: str
    model: str = "gpt-5.4-mini"
    prompt_tokens: int = 120
    completion_tokens: int = 60
    total_tokens: int = 180


class _QueueProvider:
    def __init__(self, responses: list[_FakeResponse], *, delay_seconds: float = 0.0) -> None:
        self._responses = list(responses)
        self._delay_seconds = delay_seconds
        self.calls: list[str] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls.append(request.prompt)
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        if not self._responses:
            raise RuntimeError("no responses remaining")
        response = self._responses.pop(0)
        return ChatCompletionResponse(
            content=response.content,
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            latency_ms=1,
        )


def _make_chunk(index: int = 1) -> CitationContextChunk:
    return CitationContextChunk(
        document_id=f"11111111-1111-1111-1111-11111111111{index}",
        chunk_id=f"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa{index}",
        filename="policy.pdf",
        page_number=index,
        text=f"Source text {index}. The policy says 30 days.",
        similarity_score=0.9 - (index * 0.02),
        original_rank=index,
        rerank_score=0.95 - (index * 0.02),
        rerank_rank=index,
        final_rank=index,
    )


def _make_citation(
    *,
    doc_id: str,
    chunk_id: str,
    source_status: str,
    doc_status: str,
    freshness_state: str,
    stale: bool = False,
) -> ChatCitationResponse:
    return ChatCitationResponse(
        document_id=doc_id,
        chunk_id=chunk_id,
        filename="policy.pdf",
        page_number=1,
        text_snippet="Policy text snippet.",
        source_trust_status=source_status,
        doc_trust_status=doc_status,
        freshness_state=freshness_state,
        doc_stale_warning=stale,
    )


def _make_candidate(
    *,
    strategy: str,
    answer: str,
    not_found: bool,
    risk_penalty: float = 0.0,
) -> TreeSearchCandidateDraft:
    llm_result = LLMAnswerResult(
        answer=answer,
        not_found=not_found,
        citations=[],
        model_name="gpt-5.4-mini",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        approximate_cost_usd=Decimal("0.01"),
        latency_ms=1,
        retry_count=0,
        used_fallback_parser=False,
        provider_key="openai",
        fallback_used=False,
    )
    return TreeSearchCandidateDraft(
        strategy=strategy,  # type: ignore[arg-type]
        strategy_label=strategy.replace("_", " ").title(),
        risk_penalty=risk_penalty,
        llm_result=llm_result,
    )


@pytest.fixture(autouse=True)
def _enable_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "feature_enable_llm", True)


def _build_service(
    provider: object, *, input_cost: float = 10.0, output_cost: float = 10.0
) -> TreeSearchService:
    llm_service = LLMService(
        provider=provider,  # type: ignore[arg-type]
        input_cost_per_million_tokens_usd=input_cost,
        output_cost_per_million_tokens_usd=output_cost,
    )
    return TreeSearchService(llm_service=llm_service, prompt_service=PromptService())


class TestTreeSearchGeneration:
    @pytest.mark.asyncio
    async def test_generate_candidates_respects_max_candidates(self) -> None:
        responses = [
            _FakeResponse(
                content='{"answer":"A","not_found":false,"citations":[]}',
            ),
            _FakeResponse(
                content='{"answer":"B","not_found":false,"citations":[]}',
            ),
            _FakeResponse(
                content='{"answer":"C","not_found":false,"citations":[]}',
            ),
        ]
        provider = _QueueProvider(responses)
        service = _build_service(provider)

        result = await service.generate_candidates(
            question="What does the policy say?",
            context_chunks=[_make_chunk(1), _make_chunk(2)],
            not_found_answer="I could not find this information in the uploaded documents.",
            max_candidates=2,
        )

        assert result.candidate_count == 2
        assert len(provider.calls) == 2
        assert result.failed is False

    @pytest.mark.asyncio
    async def test_generate_candidates_timeout_hits_limit(self) -> None:
        provider = _QueueProvider(
            [
                _FakeResponse(
                    content='{"answer":"A","not_found":false,"citations":[]}',
                )
            ],
            delay_seconds=0.05,
        )
        service = _build_service(provider)

        result = await service.generate_candidates(
            question="What does the policy say?",
            context_chunks=[_make_chunk(1), _make_chunk(2)],
            not_found_answer="I could not find this information in the uploaded documents.",
            timeout_seconds=0.01,
        )

        assert result.candidate_count == 0
        assert result.timeout_hit is True
        assert result.failed is True

    @pytest.mark.asyncio
    async def test_generate_candidates_cost_limit_hits_after_first_call(self) -> None:
        provider = _QueueProvider(
            [
                _FakeResponse(
                    content='{"answer":"A","not_found":false,"citations":[]}',
                ),
                _FakeResponse(
                    content='{"answer":"B","not_found":false,"citations":[]}',
                ),
            ]
        )
        service = _build_service(provider, input_cost=2500.0, output_cost=2500.0)

        result = await service.generate_candidates(
            question="What does the policy say?",
            context_chunks=[_make_chunk(1), _make_chunk(2)],
            not_found_answer="I could not find this information in the uploaded documents.",
            max_total_cost_usd=Decimal("0.001"),
        )

        assert result.candidate_count == 1
        assert result.cost_limit_hit is True
        assert len(provider.calls) == 1


class TestTreeSearchScoring:
    def setup_method(self) -> None:
        self.service = _build_service(
            _QueueProvider([]),  # type: ignore[arg-type]
        )
        self.signals = [
            ConfidenceChunkSignal(similarity_score=0.95, rerank_score=0.93),
            ConfidenceChunkSignal(similarity_score=0.91, rerank_score=0.90),
        ]

    def test_scoring_prefers_trusted_supported_candidate(self) -> None:
        conservative = _make_candidate(
            strategy="conservative",
            answer="The policy says 30 days.",
            not_found=False,
            risk_penalty=0.0,
        )
        conservative_citations = [
            _make_citation(
                doc_id="doc-1",
                chunk_id="chunk-1",
                source_status="trusted",
                doc_status="current",
                freshness_state="current",
            )
        ]
        balanced = _make_candidate(
            strategy="balanced",
            answer="The policy may be 30 days or 60 days.",
            not_found=False,
            risk_penalty=0.05,
        )
        balanced_citations = [
            _make_citation(
                doc_id="doc-2",
                chunk_id="chunk-2",
                source_status="stale",
                doc_status="stale",
                freshness_state="stale",
                stale=True,
            )
        ]

        conservative_score = self.service.score_candidate(
            candidate=conservative,
            citations=conservative_citations,
            confidence_signals=self.signals,
            citation_validation_score=1.0,
            freshness_multiplier=1.0,
            ocr_quality_multiplier=1.0,
            conflict_multiplier=1.0,
            table_quality_multiplier=1.0,
            extraction_quality_multiplier=1.0,
            graph_context_used=False,
        )
        balanced_score = self.service.score_candidate(
            candidate=balanced,
            citations=balanced_citations,
            confidence_signals=self.signals,
            citation_validation_score=0.5,
            freshness_multiplier=0.7,
            ocr_quality_multiplier=1.0,
            conflict_multiplier=0.8,
            table_quality_multiplier=1.0,
            extraction_quality_multiplier=1.0,
            graph_context_used=False,
        )

        assert conservative_score.score > balanced_score.score

    def test_not_found_candidate_wins_when_evidence_is_weak(self) -> None:
        refusal = _make_candidate(
            strategy="conservative",
            answer="",
            not_found=True,
            risk_penalty=0.0,
        )
        refusal_score = self.service.score_candidate(
            candidate=refusal,
            citations=[],
            confidence_signals=[],
            citation_validation_score=1.0,
            freshness_multiplier=1.0,
            ocr_quality_multiplier=1.0,
            conflict_multiplier=1.0,
            table_quality_multiplier=1.0,
            extraction_quality_multiplier=1.0,
            graph_context_used=False,
        )
        assert refusal_score.not_found is True
        hallucinated = _make_candidate(
            strategy="balanced",
            answer="The answer is definitely 45 days.",
            not_found=False,
            risk_penalty=0.1,
        )
        hallucinated_score = self.service.score_candidate(
            candidate=hallucinated,
            citations=[
                _make_citation(
                    doc_id="doc-9",
                    chunk_id="chunk-9",
                    source_status="stale",
                    doc_status="stale",
                    freshness_state="stale",
                    stale=True,
                )
            ],
            confidence_signals=[],
            citation_validation_score=0.2,
            freshness_multiplier=0.6,
            ocr_quality_multiplier=1.0,
            conflict_multiplier=0.6,
            table_quality_multiplier=1.0,
            extraction_quality_multiplier=1.0,
            graph_context_used=False,
        )
        assert refusal_score.score >= hallucinated_score.score

    def test_select_candidate_rejects_low_score_below_threshold(self) -> None:
        weak = _make_candidate(
            strategy="balanced",
            answer="Maybe.",
            not_found=False,
            risk_penalty=0.1,
        )
        weak_score = self.service.score_candidate(
            candidate=weak,
            citations=[],
            confidence_signals=[],
            citation_validation_score=0.1,
            freshness_multiplier=0.5,
            ocr_quality_multiplier=1.0,
            conflict_multiplier=0.5,
            table_quality_multiplier=1.0,
            extraction_quality_multiplier=1.0,
            graph_context_used=False,
        )

        selection = self.service.select_candidate([weak_score], min_selected_score=0.9)
        assert selection.accepted is False
        assert selection.selection_reason == "below_threshold"
