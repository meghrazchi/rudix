"""Recording fake chat provider for the chat golden transcripts (R05-01)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest
from test_chat_query_api import (
    _FakeEmbeddingProvider,
)

from app.core.config import settings
from app.domains.ai.providers.errors import ProviderTimeoutError
from app.domains.ai.providers.factory import default_provider_factory
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.interfaces.http import chat as chat_api

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "chat_golden"
UPDATE_ENV = "CHAT_GOLDEN_UPDATE"
_GOLDEN_NAMESPACE = UUID("6f1d3a52-6c4e-4d61-9a43-5a1d0c2b7e10")

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# ---------------------------------------------------------------------------
# Recording provider
# ---------------------------------------------------------------------------

PROMPT_KINDS = (
    "rerank",
    "rewrite",
    "conflict",
    "verifier",
    "refiner",
    "guidance",
    "tree_search",
    "answer",
)

_KIND_MARKERS: tuple[tuple[str, str], ...] = (
    ("You are reranking retrieved document chunks", "rerank"),
    ("You are a search-query optimizer", "rewrite"),
    ("You are a source-conflict analyst", "conflict"),
    ("You are a grounded-answer fact-checker", "verifier"),
    ("You are an answer refiner", "refiner"),
    ("You are a Rudix product guidance assistant", "guidance"),
    ("Tree-search mode:", "tree_search"),
)

_KIND_TOKENS: dict[str, tuple[int, int]] = {
    "rerank": (19, 7),
    "rewrite": (23, 11),
    "conflict": (29, 13),
    "verifier": (13, 9),
    "refiner": (17, 8),
    "guidance": (21, 12),
    "tree_search": (37, 19),
    "answer": (31, 17),
}

Responder = Callable[[str], str]


def prompt_kind(prompt: str) -> str:
    for marker, kind in _KIND_MARKERS:
        if marker in prompt:
            return kind
    return "answer"


def context_blocks(prompt: str) -> list[dict[str, str]]:
    """Parse the ``[n]`` context blocks of an answer prompt (document_id, chunk_id, text)."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    reading_text = False
    for line in prompt.splitlines():
        if re.fullmatch(r"\[\d+\]", line.strip()):
            current = {}
            blocks.append(current)
            reading_text = False
            continue
        if current is None:
            continue
        if reading_text:
            if line.strip() and not line.startswith("<<") and "text" not in current:
                current["text"] = line.strip()
            reading_text = False
            continue
        if line.startswith("text:"):
            reading_text = True
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            if key in {"document_id", "chunk_id", "filename", "page_number"}:
                current[key] = value.strip()
    return [block for block in blocks if "chunk_id" in block]


def cite_first_chunk(prompt: str) -> str:
    blocks = context_blocks(prompt)
    if not blocks:
        return json.dumps({"answer": "", "not_found": True, "citations": []})
    first = blocks[0]
    text = first.get("text", "")
    return json.dumps(
        {
            "answer": text,
            "not_found": False,
            "citations": [
                {
                    "document_id": first["document_id"],
                    "chunk_id": first["chunk_id"],
                    "text_snippet": text[:80],
                }
            ],
        }
    )


def _rerank_scores(prompt: str) -> str:
    keys = [
        line.split(":", 1)[1].strip() for line in prompt.splitlines() if line.startswith("key:")
    ]
    scores = [
        {"key": key, "score": round(max(0.1, 0.92 - (index * 0.01)), 2)}
        for index, key in enumerate(keys)
    ]
    return json.dumps({"scores": scores})


def _rewrite_original(prompt: str) -> str:
    question = prompt.rsplit("User question:", 1)[-1].strip()
    return json.dumps({"strategy": "original", "primary_query": question, "sub_queries": []})


def _conflict_full(_prompt: str) -> str:
    return json.dumps(
        {
            "agreement_level": "full",
            "conflict_pairs": [],
            "conflict_summary": "",
            "preferred_doc_labels": [],
        }
    )


def _verifier_supported(prompt: str) -> str:
    answer = ""
    if "GENERATED ANSWER" in prompt:
        answer = prompt.split("GENERATED ANSWER", 1)[1].split("\n\n", 1)[0]
        answer = answer.lstrip(":\n ").strip()
    return json.dumps(
        {
            "verdict": "supported",
            "revised_answer": answer,
            "removed_claims": [],
            "reason_codes": [],
            "claim_count": 1,
            "supported_claim_count": 1,
            "partially_supported_claim_count": 0,
            "unsupported_claim_count": 0,
            "unverifiable_claim_count": 0,
        }
    )


def _refiner_unchanged(prompt: str) -> str:
    draft = prompt.split("DRAFT ANSWER:\n", 1)[-1].split("\n\n", 1)[0].strip()
    return json.dumps(
        {"refined_answer": draft, "changes_made": [], "unsupported_claims_removed": 0}
    )


def _guidance_answer(_prompt: str) -> str:
    return json.dumps(
        {
            "answer": "Use the source scope menu to narrow the documents shown in chat.",
            "not_found": False,
            "citations": [],
        }
    )


DEFAULT_RESPONDERS: dict[str, Responder] = {
    "rerank": _rerank_scores,
    "rewrite": _rewrite_original,
    "conflict": _conflict_full,
    "verifier": _verifier_supported,
    "refiner": _refiner_unchanged,
    "guidance": _guidance_answer,
    "tree_search": cite_first_chunk,
    "answer": cite_first_chunk,
}


class RecordingChatProvider:
    """One fake chat provider for every prompt kind; records each request."""

    def __init__(
        self,
        *,
        responders: dict[str, Responder] | None = None,
        fail_kinds: frozenset[str] = frozenset(),
    ) -> None:
        self._responders = {**DEFAULT_RESPONDERS, **(responders or {})}
        self._fail_kinds = fail_kinds
        self.calls: list[tuple[str, ChatCompletionRequest]] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        kind = prompt_kind(request.prompt)
        self.calls.append((kind, request))
        if kind in self._fail_kinds:
            raise ProviderTimeoutError(f"scripted {kind} failure")
        prompt_tokens, completion_tokens = _KIND_TOKENS[kind]
        return ChatCompletionResponse(
            content=self._responders[kind](request.prompt),
            model=settings.openai_llm_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=5,
        )


def install_providers(
    monkeypatch: pytest.MonkeyPatch, provider: RecordingChatProvider
) -> _FakeEmbeddingProvider:
    embed_provider = _FakeEmbeddingProvider()
    default_provider_factory._chat_providers.clear()
    default_provider_factory._chat_providers[settings.llm_default_provider] = provider
    default_provider_factory._chat_providers[settings.rerank_default_provider] = provider
    monkeypatch.setattr(chat_api._llm_service, "_provider", provider)
    monkeypatch.setattr(chat_api._query_retrieval_service, "_embedding_provider", embed_provider)
    return embed_provider
