"""R05-08: auxiliary chat stages run on the resolved ``chat`` model profile.

With ``LLM_DEFAULT_PROVIDER=local`` and every auxiliary stage on, no provider request names
``OPENAI_LLM_MODEL`` and the OpenAI provider is never built. Without a profile (callers
outside the pipeline) the services keep the environment default.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from chat_aux_support import (
    AUX_RESPONDERS,
    EXPECTED_AUX_KINDS,
    ask_aux_questions,
    enable_all_aux_stages,
    install_chat_provider,
)
from chat_golden_providers import RecordingChatProvider
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import chat_query_client  # noqa: F401  (pytest fixture re-export)

from app.core.config import settings
from app.domains.ai.profile.schemas import ProfileSource, ResolvedTaskProfile, TaskType
from app.domains.ai.providers.factory import default_provider_factory
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.domains.chat.services.answer_refiner_service import AnswerRefinerService
from app.domains.chat.services.aux_llm import estimate_llm_cost, resolve_aux_route
from app.domains.chat.services.conflict_detection_service import (
    ConflictDetectionChunk,
    ConflictDetectionService,
)
from app.domains.chat.services.grounded_answer_verifier import (
    GroundedAnswerVerifier,
    VerifierChunk,
)
from app.domains.chat.services.query_rewriting_service import QueryRewritingService
from app.domains.chat.services.rerank_service import (
    RerankCandidate,
    RerankService,
    RerankSettings,
)

LOCAL_MODEL = "local-routing-model"


def _never_build_openai() -> None:
    raise AssertionError("the OpenAI chat provider must not be built")


@pytest.mark.asyncio
async def test_local_default_provider_routes_every_aux_stage_to_the_profile(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_default_provider", "local")
    monkeypatch.setattr(settings, "local_llm_model", LOCAL_MODEL)
    assert LOCAL_MODEL != settings.openai_llm_model
    enable_all_aux_stages(monkeypatch)
    monkeypatch.setattr(
        default_provider_factory, "_build_openai_chat_provider", _never_build_openai
    )
    provider = RecordingChatProvider(responders=AUX_RESPONDERS)
    install_chat_provider(monkeypatch, provider, provider_key="local")

    await ask_aux_questions(client=chat_query_client, db_session=db_session, provider=provider)

    kinds = {kind for kind, _ in provider.calls}
    assert EXPECTED_AUX_KINDS <= kinds, kinds
    models = {(kind, request.model) for kind, request in provider.calls}
    assert all(model == LOCAL_MODEL for _, model in models), models
    assert not [r for _, r in provider.calls if r.model == settings.openai_llm_model]
    assert set(default_provider_factory._chat_providers) == {"local"}


def _profile(provider_type: str = "local", model: str = LOCAL_MODEL) -> ResolvedTaskProfile:
    return ResolvedTaskProfile(
        task_type=TaskType.chat,
        provider_type=provider_type,
        base_model=model,
        json_mode=True,
        streaming=True,
        source=ProfileSource.org_profile,
        version=1,
    )


class _KeyedFactory:
    """Records the provider key each service asks for."""

    def __init__(self, provider: object) -> None:
        self.keys: list[str | None] = []
        self._provider = provider

    def get_chat_provider(self, provider_key: str | None = None) -> object:
        self.keys.append(provider_key)
        return self._provider


class _JsonProvider:
    def __init__(self, content: str, *, prompt_tokens: int = 11, completion: int = 5) -> None:
        self.requests: list[ChatCompletionRequest] = []
        self._content = content
        self._prompt_tokens = prompt_tokens
        self._completion = completion

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.requests.append(request)
        return ChatCompletionResponse(
            content=self._content,
            model=request.model,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion,
            total_tokens=self._prompt_tokens + self._completion,
            latency_ms=1,
        )


def test_resolve_aux_route_uses_profile_or_env_default() -> None:
    routed = resolve_aux_route(_profile())
    assert (routed.provider_key, routed.model_name) == ("local", LOCAL_MODEL)
    assert routed.reported_provider_key == "local"
    default = resolve_aux_route(None)
    assert default.provider_key is None
    assert default.model_name == settings.openai_llm_model
    assert default.reported_provider_key == settings.llm_default_provider


def test_estimate_llm_cost_uses_configured_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_llm_input_cost_per_million_tokens_usd", 2.0)
    monkeypatch.setattr(settings, "openai_llm_output_cost_per_million_tokens_usd", 8.0)
    assert estimate_llm_cost(1_000_000, 500_000) == Decimal("6")


@pytest.mark.asyncio
async def test_services_route_to_profile_and_report_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _JsonProvider('{"strategy": "original", "primary_query": "q", "sub_queries": []}')
    factory = _KeyedFactory(provider)
    monkeypatch.setattr(default_provider_factory, "get_chat_provider", factory.get_chat_provider)

    rewrite = await QueryRewritingService().rewrite("q", resolved_profile=_profile())
    assert rewrite.usage is not None and rewrite.usage.prompt_tokens == 11
    assert (rewrite.provider_key, rewrite.model_name) == ("local", LOCAL_MODEL)

    provider._content = '{"agreement_level": "full", "conflict_pairs": []}'
    conflict = await ConflictDetectionService().detect(
        chunks=[
            ConflictDetectionChunk(chunk_id="c1", document_id="d1", text="A"),
            ConflictDetectionChunk(chunk_id="c2", document_id="d2", text="B"),
        ],
        min_source_docs=2,
        resolved_profile=_profile(),
    )
    assert conflict.applied and conflict.usage is not None
    assert conflict.model_name == LOCAL_MODEL

    provider._content = '{"verdict": "supported", "revised_answer": "A"}'
    verified = await GroundedAnswerVerifier().verify(
        answer="A",
        chunks=[VerifierChunk(chunk_id="c1", text="A")],
        resolved_profile=_profile(),
    )
    assert verified.applied and verified.usage is not None
    assert (verified.provider_key, verified.model_name) == ("local", LOCAL_MODEL)

    provider._content = '{"refined_answer": "A", "changes_made": []}'
    refined = await AnswerRefinerService().refine(
        draft_answer="A",
        critic_instruction="fix",
        citation_snippets=["A"],
        resolved_profile=_profile(),
    )
    assert refined.applied and refined.usage is not None
    assert (refined.provider_key, refined.model_name) == ("local", LOCAL_MODEL)

    assert factory.keys == ["local", "local", "local", "local"]
    assert {r.model for r in provider.requests} == {LOCAL_MODEL}


@pytest.mark.asyncio
async def test_services_without_profile_keep_env_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _JsonProvider("not json")
    factory = _KeyedFactory(provider)
    monkeypatch.setattr(default_provider_factory, "get_chat_provider", factory.get_chat_provider)

    rewrite = await QueryRewritingService().rewrite("q")
    # A completed call that fails to parse still reports its usage.
    assert rewrite.strategy == "original" and rewrite.usage is not None
    conflict = await ConflictDetectionService().detect(
        chunks=[
            ConflictDetectionChunk(chunk_id="c1", document_id="d1", text="A"),
            ConflictDetectionChunk(chunk_id="c2", document_id="d2", text="B"),
        ],
        min_source_docs=2,
    )
    assert not conflict.applied and conflict.usage is not None
    verified = await GroundedAnswerVerifier().verify(
        answer="A", chunks=[VerifierChunk(chunk_id="c1", text="A")]
    )
    assert not verified.applied and verified.usage is not None
    refined = await AnswerRefinerService().refine(
        draft_answer="A", critic_instruction="fix", citation_snippets=["A"]
    )
    assert not refined.applied and refined.usage is not None

    assert factory.keys == [None, None, None, None]
    assert {r.model for r in provider.requests} == {settings.openai_llm_model}


@pytest.mark.asyncio
async def test_rerank_routes_to_profile_and_records_each_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rerank_default_provider", "openai")
    candidates = [
        RerankCandidate(key=f"k{i}", text=f"text {i}", similarity_score=0.9 - i * 0.1)
        for i in range(2)
    ]
    factory = _KeyedFactory(None)
    service = RerankService(provider_factory=factory)

    class _PerBatch:
        def __init__(self) -> None:
            self.requests: list[ChatCompletionRequest] = []

        async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
            self.requests.append(request)
            key = request.prompt.split("key: ", 1)[1].split("\n", 1)[0]
            return ChatCompletionResponse(
                content=f'{{"scores": [{{"key": "{key}", "score": 0.7}}]}}',
                model=request.model,
                prompt_tokens=19,
                completion_tokens=7,
                total_tokens=26,
                latency_ms=1,
            )

    per_batch = _PerBatch()
    factory._provider = per_batch
    result = await service.rerank(
        query="q",
        candidates=candidates,
        enabled=True,
        final_top_k=2,
        settings_override=RerankSettings(enabled=True, batch_size=1),
        resolved_profile=_profile(),
    )
    assert factory.keys == ["local"]
    assert {r.model for r in per_batch.requests} == {LOCAL_MODEL}
    usages = result.diagnostics.batch_usages
    assert [(u.provider_key, u.model_name, u.prompt_tokens) for u in usages] == [
        ("local", LOCAL_MODEL, 19),
        ("local", LOCAL_MODEL, 19),
    ]
    # Diagnostics keep reporting the configured rerank model (none configured here).
    assert result.diagnostics.model_name is None
    assert result.diagnostics.prompt_tokens == 38


@pytest.mark.asyncio
async def test_rerank_route_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    service = RerankService(
        provider_factory=_KeyedFactory(None),
        default_provider_key="openai",
        default_model_name="rerank-env-model",
    )
    configured = RerankSettings(enabled=True, provider_key="local", model_name="rag-model")
    assert service._route(configured, _profile()) == ("local", "rag-model")
    assert service._route(RerankSettings(enabled=True), _profile()) == ("local", LOCAL_MODEL)
    openai_profile = _profile("openai", "gpt-profile")
    assert service._route(RerankSettings(enabled=True), openai_profile) == (
        "openai",
        "rerank-env-model",
    )
    assert service._route(RerankSettings(enabled=True), None) == ("openai", "rerank-env-model")
