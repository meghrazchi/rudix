"""Compatibility surface of ``app.interfaces.http.chat`` (R05-01, contract 4.2.2).

S1 defines it, S3 keeps it. Tests and the bot service reach the chat pipeline through these
names, so they must stay importable and bound to the objects the pipeline uses.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from app.application.chat.pipeline import controls
from app.application.chat.pipeline.deps import default_deps
from app.domains.ai.providers.protocols import ChatCompletionRequest, EmbeddingRequest
from app.interfaces.http import chat as chat_api

SAME_OBJECTS = {
    "_llm_service": "llm_service",
    "_query_retrieval_service": "query_retrieval_service",
    "_rerank_service": "rerank_service",
    "_grounded_verifier": "grounded_verifier",
    "_query_rewriting_service": "query_rewriting_service",
    "_graph_retrieval_service": "graph_retrieval_service",
    "_feature_flag_service": "feature_flag_service",
    "chat_repository": "chat_repository",
}

REBINDABLE_GLOBALS = (
    "_openai_client",
    "SessionLocal",
    "ensure_chat_quota",
    "authenticate_ws_handshake",
    "_run_ws_chat_pipeline",
)

REEXPORTED_HELPERS = (
    "_with_table_metadata",
    "_build_tool_orchestration_record",
    "_build_retrieval_method_record",
    "_resolve_planner_critic_controls",
    "_build_planner_critic_record",
    "_parse_uuid_or_none",
    "_build_conflict_context",
    "_compute_conflict_multiplier",
    "_with_conflict_status",
    # F315 names
    "_EXTRACTION_WARNING_PROFILES",
    "_PROCESSING_INCOMPLETE_STATUSES",
    "_TABLE_CONFIDENCE_LOW_THRESHOLD",
    "_build_evidence_quality_record",
    "_compute_extraction_quality_multiplier",
    "_compute_table_quality_multiplier",
    "_with_extraction_quality",
    "GraphRetrievalResult",
    "GraphRetrievedChunk",
    "AuthenticatedPrincipal",
    "settings",
)


@pytest.mark.parametrize(("module_name", "deps_name"), sorted(SAME_OBJECTS.items()))
def test_chat_module_names_are_the_pipeline_singletons(module_name: str, deps_name: str) -> None:
    assert getattr(chat_api, module_name) is getattr(default_deps, deps_name)


def test_llm_service_identity() -> None:
    assert chat_api._llm_service is default_deps.llm_service


@pytest.mark.parametrize("name", REBINDABLE_GLOBALS + REEXPORTED_HELPERS)
def test_compat_names_are_present(name: str) -> None:
    assert hasattr(chat_api, name)


def test_query_chat_and_ws_pipeline_signatures() -> None:
    assert list(inspect.signature(chat_api._run_ws_chat_pipeline).parameters) == [
        "websocket",
        "payload",
        "principal",
        "request_id",
        "sequence_start",
    ]
    assert list(inspect.signature(chat_api.query_chat).parameters) == [
        "request",
        "payload",
        "principal",
        "_",
        "db_session",
    ]
    assert callable(chat_api.chat_websocket)


def test_settings_patch_target_reaches_controls() -> None:
    assert controls.settings is chat_api.settings


class _FakeOpenAI:
    def __init__(self) -> None:
        self.chat_calls: list[dict[str, Any]] = []
        self.embedding_calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._embed)

    async def _create(self, **kwargs: Any) -> Any:
        self.chat_calls.append(kwargs)
        message = SimpleNamespace(content='{"answer":"ok","not_found":false,"citations":[]}')
        usage = SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)], usage=usage, model="fake-model"
        )

    async def _embed(self, **kwargs: Any) -> Any:
        self.embedding_calls.append(kwargs)
        usage = SimpleNamespace(prompt_tokens=4, total_tokens=4)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2])], usage=usage, model="fake-embed"
        )


async def test_setattr_openai_client_reaches_the_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeOpenAI()
    monkeypatch.setattr(chat_api, "_openai_client", fake)

    chat_provider = chat_api._llm_service._resolve_provider(None)
    response = await chat_provider.complete(
        ChatCompletionRequest(prompt="question", model="m", json_mode=True, max_tokens=10)
    )
    assert response.model == "fake-model"
    assert response.total_tokens == 5
    assert fake.chat_calls[0]["response_format"] == {"type": "json_object"}
    assert fake.chat_calls[0]["max_tokens"] == 10

    embed_provider = chat_api._query_retrieval_service._resolve_embedding_provider()
    embedded = await embed_provider.embed(EmbeddingRequest(texts=["q"], model="e"))
    assert embedded.vectors == [[0.1, 0.2]]
    assert embedded.prompt_tokens == 4

    # A cleared injected provider falls back to a proxy while the client is set.
    monkeypatch.setattr(chat_api._llm_service, "_provider", None)
    monkeypatch.setattr(chat_api._query_retrieval_service, "_embedding_provider", None)
    assert isinstance(
        chat_api._llm_service._resolve_provider(None), chat_api._ChatCompletionProviderProxy
    )
    assert isinstance(
        chat_api._query_retrieval_service._resolve_embedding_provider(),
        chat_api._EmbeddingProviderProxy,
    )


async def test_cleared_openai_client_routes_to_the_provider_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_chat = object()
    sentinel_embed = object()
    factory = default_deps_factory_stub(sentinel_chat, sentinel_embed)
    monkeypatch.setattr(
        "app.application.chat.pipeline.provider_proxies.default_provider_factory", factory
    )
    monkeypatch.setattr(chat_api, "_openai_client", None)
    monkeypatch.setattr(chat_api._llm_service, "_provider", None)
    monkeypatch.setattr(chat_api._query_retrieval_service, "_embedding_provider", None)
    assert chat_api._llm_service._resolve_provider("openai") is sentinel_chat
    assert chat_api._query_retrieval_service._resolve_embedding_provider() is sentinel_embed

    recorded: list[ChatCompletionRequest] = []

    class _Provider:
        async def complete(self, request: ChatCompletionRequest) -> str:
            recorded.append(request)
            return "routed"

        async def embed(self, request: EmbeddingRequest) -> str:
            return "embedded"

    routed = default_deps_factory_stub(_Provider(), _Provider())
    monkeypatch.setattr(
        "app.application.chat.pipeline.provider_proxies.default_provider_factory", routed
    )
    proxy = chat_api._ChatCompletionProviderProxy(lambda: chat_api._openai_client)
    request = ChatCompletionRequest(prompt="p", model="m")
    assert await proxy.complete(request) == "routed"
    assert recorded == [request]
    embed_proxy = chat_api._EmbeddingProviderProxy(lambda: chat_api._openai_client)
    assert await embed_proxy.embed(EmbeddingRequest(texts=["q"], model="e")) == "embedded"


def default_deps_factory_stub(chat_provider: object, embed_provider: object) -> Any:
    return SimpleNamespace(
        get_chat_provider=lambda _key=None: chat_provider,
        get_embedding_provider=lambda: embed_provider,
    )
