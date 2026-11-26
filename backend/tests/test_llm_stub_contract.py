"""Contract tests for the test-only OpenAI-compatible stub (ci/stubs/llm_stub.py, R03-04).

The stub replaces the real model in the integration e2e stack and the load harness. These tests
prove its answers pass the backend's own prompt builder, answer parser, citation validation,
reranker parsing, and embedding adapter, so the e2e suite exercises the real pipeline.
"""

from __future__ import annotations

import importlib.util
import json
import math
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from openai import AsyncOpenAI

from app.domains.ai.providers.local.adapter import OpenAICompatibleChatProvider
from app.domains.ai.providers.local.embedding_adapter import OpenAICompatibleEmbeddingProvider
from app.domains.ai.providers.protocols import EmbeddingRequest
from app.domains.chat.services.citation_service import CitationContextChunk, CitationService
from app.domains.chat.services.llm_service import LLMService
from app.domains.chat.services.prompt_service import PromptContextChunk, PromptService
from app.domains.chat.services.rerank_service import RerankCandidate, RerankService

_STUB_PATH = Path(__file__).resolve().parents[2] / "ci" / "stubs" / "llm_stub.py"
_NOT_FOUND = "I could not find this information in the uploaded documents."
_FACT = "The Rudix integration verification code is AURORA-7319."


def _load_stub() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rudix_llm_stub", _STUB_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def stub() -> ModuleType:
    return _load_stub()


@pytest.fixture
def stub_url(stub: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.delenv("STUB_LLM_LATENCY_MS", raising=False)
    monkeypatch.delenv("STUB_LLM_LATENCY_JITTER_MS", raising=False)
    monkeypatch.delenv("STUB_EMBEDDING_DIM", raising=False)
    server = stub.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _client(stub_url: str) -> Any:
    # Any: the adapters take structural client protocols that AsyncOpenAI satisfies at runtime.
    return AsyncOpenAI(api_key="not-required", base_url=f"{stub_url}/v1", max_retries=0)


def _chunks() -> list[CitationContextChunk]:
    document_id = uuid4()
    return [
        CitationContextChunk(
            document_id=document_id,
            chunk_id=uuid4(),
            filename="rudix-e2e.txt",
            page_number=None,
            text=f"{_FACT} It is used only by the end-to-end suite.",
            similarity_score=0.82,
            original_rank=1,
        ),
        CitationContextChunk(
            document_id=document_id,
            chunk_id=uuid4(),
            filename="rudix-e2e.txt",
            page_number=2,
            text="A second paragraph that talks about unrelated onboarding steps.",
            similarity_score=0.41,
            original_rank=2,
        ),
    ]


def _prompt(chunks: list[CitationContextChunk]) -> str:
    return PromptService().build_prompt(
        question="What is the Rudix integration verification code?",
        chunks=[
            PromptContextChunk(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=chunk.original_rank,
            )
            for chunk in chunks
        ],
        not_found_answer=_NOT_FOUND,
    )


def _http(url: str, body: dict[str, Any] | bytes | None = None) -> tuple[int, bytes]:
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


async def test_answer_round_trip_passes_parser_and_citation_validation(stub_url: str) -> None:
    chunks = _chunks()
    provider = OpenAICompatibleChatProvider(client=_client(stub_url), model_name="stub-chat")
    result = await LLMService(provider=provider, retry_max_attempts=1).generate_answer(
        prompt=_prompt(chunks)
    )

    assert result.not_found is False
    assert result.used_fallback_parser is False
    assert "AURORA-7319" in result.answer
    assert result.prompt_tokens > 0 and result.completion_tokens > 0

    built = CitationService().build_citations(
        not_found=result.not_found,
        answer=result.answer,
        retrieved_chunks=chunks,
        model_citations=result.citations,
    )
    allowed = {str(chunk.chunk_id) for chunk in chunks}
    assert built.used_fallback is False
    assert built.accepted_model_citation_count == 1
    assert built.invalid_chunk_id_count == 0
    assert built.metadata_mismatch_count == 0
    assert built.snippet_mismatch_count == 0
    assert built.validation_score == 1.0
    assert built.citations[0].chunk_id in allowed
    assert built.citations[0].chunk_id == str(chunks[0].chunk_id)
    assert built.citations[0].filename == "rudix-e2e.txt"


def test_prompt_without_chunks_gives_not_found(stub: ModuleType) -> None:
    content = stub.completion_content([{"role": "user", "content": _prompt([])}], True)
    parsed = LLMService._parse_strict_output(content)

    assert parsed.not_found is True
    assert parsed.answer == _NOT_FOUND
    assert parsed.citations == []
    built = CitationService().build_citations(
        not_found=parsed.not_found,
        answer=parsed.answer,
        retrieved_chunks=[],
        model_citations=parsed.citations,
    )
    assert built.citations == []


def test_answer_prompt_without_template_markers_uses_default_not_found(stub: ModuleType) -> None:
    payload = stub.answer_payload("Return keys: answer, not_found, citations")
    assert payload == {"answer": stub.DEFAULT_NOT_FOUND_ANSWER, "not_found": True, "citations": []}
    # Allowed ids without any context block (or a forged id) never produce a citation.
    forged = stub.answer_payload("Allowed citation chunk_ids:\nabc\n\nContext blocks:\n<none>")
    assert forged["not_found"] is True and forged["citations"] == []


async def test_rerank_prompt_returns_identity_ranking(stub_url: str) -> None:
    provider = OpenAICompatibleChatProvider(client=_client(stub_url), model_name="stub-chat")
    batch = [
        RerankCandidate(key=f"chunk-{index}", text=f"text {index}", similarity_score=0.5)
        for index in range(3)
    ]
    scores, prompt_tokens, _, _ = await RerankService()._score_batch(
        query="verification code",
        batch=batch,
        provider=provider,
        model_name="stub-chat",
        timeout_seconds=5.0,
        max_candidate_chars=2000,
    )

    assert [score.key for score in scores] == ["chunk-0", "chunk-1", "chunk-2"]
    assert scores[0].score > scores[1].score > scores[2].score
    assert prompt_tokens > 0


def test_other_prompts_return_minimal_completion(stub: ModuleType) -> None:
    messages = [{"role": "user", "content": "Rewrite this query."}]
    assert stub.completion_content(messages, True) == "{}"
    assert stub.completion_content(messages, False) == "OK"


async def test_embeddings_have_configured_dimension_and_are_deterministic(
    stub: ModuleType, stub_url: str
) -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        client=_client(stub_url), model_name="stub-embedding"
    )
    texts = ["Rudix verification code", "Rudix verification code", "unrelated words"]
    response = await provider.embed(EmbeddingRequest(texts=texts))

    assert len(response.vectors) == 3
    assert all(len(vector) == 1536 for vector in response.vectors)
    assert response.vectors[0] == response.vectors[1]
    assert response.vectors[0] != response.vectors[2]
    assert math.isclose(math.fsum(v * v for v in response.vectors[0]), 1.0, rel_tol=1e-5)
    assert response.vectors[0] == pytest.approx(stub.embed_text(texts[0], 1536), abs=1e-6)


def test_embedding_dimension_env_and_float_format(
    stub: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUB_EMBEDDING_DIM", "64")
    payload = stub.embeddings({"input": "single text", "model": "m"})
    assert payload["model"] == "m"
    assert len(payload["data"]) == 1
    assert len(payload["data"][0]["embedding"]) == 64
    assert payload["usage"] == {"prompt_tokens": 2, "total_tokens": 2}
    assert len(stub.embeddings({"input": ["a"], "dimensions": 8})["data"][0]["embedding"]) == 8
    assert stub.embed_text("", 4) == [1.0, 0.0, 0.0, 0.0]


def test_latency_env_is_honoured(stub: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setenv("STUB_LLM_LATENCY_MS", "250")
    monkeypatch.setenv("STUB_LLM_LATENCY_JITTER_MS", "100")

    seconds = stub.simulate_latency(sleep=slept.append, rng=lambda low, high: high)
    assert seconds == pytest.approx(0.35)
    assert slept == [pytest.approx(0.35)]

    monkeypatch.setenv("STUB_LLM_LATENCY_MS", "not-a-number")
    monkeypatch.setenv("STUB_LLM_LATENCY_JITTER_MS", "0")
    slept.clear()
    assert stub.simulate_latency(sleep=slept.append) == 0.0
    assert slept == []


def test_http_round_trip_health_models_errors_and_stream(stub: ModuleType, stub_url: str) -> None:
    status, body = _http(f"{stub_url}/health")
    assert (status, json.loads(body)) == (200, {"status": "ok"})

    status, body = _http(f"{stub_url}/v1/models")
    assert status == 200
    assert [m["id"] for m in json.loads(body)["data"]] == ["stub-chat", "stub-embedding"]

    assert _http(f"{stub_url}/missing")[0] == 404
    assert _http(f"{stub_url}/v1/missing", {"a": 1})[0] == 404
    assert _http(f"{stub_url}/v1/chat/completions", b"not json")[0] == 400
    assert _http(f"{stub_url}/v1/embeddings", b"")[0] == 400

    chunks = _chunks()
    request = {
        "model": "stub-chat",
        "stream": True,
        "messages": [{"role": "user", "content": _prompt(chunks)}],
    }
    status, body = _http(f"{stub_url}/v1/chat/completions", request)
    assert status == 200
    events = [line[6:] for line in body.decode().splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    content = "".join(
        json.loads(event)["choices"][0]["delta"].get("content", "") for event in events[:-1]
    )
    parsed = LLMService._parse_strict_output(content)
    assert parsed.citations[0].chunk_id == str(chunks[0].chunk_id)
