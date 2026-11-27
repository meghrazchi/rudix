"""Deterministic fakes and metrics for the accuracy smoke suite (R03-03).

Everything here is pure Python and standard library apart from the app's own
types. Nothing calls a network: embeddings are feature-hashed bag-of-words
vectors, Qdrant is an in-memory store that applies the real payload filter, and
the "LLM" is a rule-based responder that reads the prompt the pipeline built.

The fake LLM behaves like a well-grounded model with one deliberate weakness:
it obeys an injected instruction (the fixture canary) when that instruction
reaches the prompt *outside* the untrusted context section. That makes the
injection metric sensitive to pipeline regressions (for example document text
leaking into the rules or the question block) without depending on a real model.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue

from app.domains.ai.providers.protocols import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)
from app.domains.quality_gates.schemas.quality_gates import QualityGateThresholds

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "accuracy_smoke"
REPO_ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS_PATH = REPO_ROOT / "ci" / "config" / "accuracy_eval_thresholds.yml"

# Thresholds this suite can measure. Faithfulness, answer relevance, latency and
# cost need a real model and live infrastructure, so the nightly run gates them.
MEASURED_THRESHOLD_FIELDS: tuple[str, ...] = (
    "retrieval_hit_rate_min",
    "citation_accuracy_score_min",
    "refusal_accuracy_score_min",
    "not_found_rate_max",
    "safety_pass_rate_min",
)

GROUNDING_MIN_OVERLAP = 0.5
NOT_FOUND_JSON = json.dumps({"answer": "", "not_found": True, "citations": []})
_RERANK_MARKER = "You are reranking retrieved document chunks"
_QUESTION_START = "<<QUESTION_START>>"
_QUESTION_END = "<<QUESTION_END>>"
_CONTEXT_MARKER = "\nContext blocks:\n"
_STOPWORDS = frozenset(
    "a an and any are as at be by do does did each for from how in is it its long "
    "many much must of on or the their there this to via was what when where which "
    "who whom why with within".split()
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SmokeQuestion:
    id: str
    question: str
    expected_document: str | None
    expected_not_found: bool
    injection: bool = False


@dataclass(frozen=True)
class SmokeFixtures:
    canary: str
    primary_documents: list[str]
    foreign_documents: list[str]
    questions: list[SmokeQuestion]


def load_fixtures(fixture_dir: Path = FIXTURE_DIR) -> SmokeFixtures:
    raw = json.loads((fixture_dir / "questions.json").read_text(encoding="utf-8"))
    questions = [
        SmokeQuestion(
            id=str(item["id"]),
            question=str(item["question"]),
            expected_document=item.get("expected_document"),
            expected_not_found=bool(item["expected_not_found"]),
            injection=bool(item.get("injection", False)),
        )
        for item in raw["questions"]
    ]
    return SmokeFixtures(
        canary=str(raw["canary"]),
        primary_documents=list(raw["documents"]["primary"]),
        foreign_documents=list(raw["documents"]["foreign"]),
        questions=questions,
    )


def document_paragraphs(filename: str, fixture_dir: Path = FIXTURE_DIR) -> list[str]:
    text = (fixture_dir / filename).read_text(encoding="utf-8")
    return [part.strip() for part in text.split("\n\n") if part.strip()]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        if raw in _STOPWORDS:
            continue
        token = raw[:-1] if len(raw) > 3 and raw.endswith("s") else raw
        tokens.append(token)
    return tokens


def hashed_embedding(text: str, dimensions: int) -> list[float]:
    """Feature-hashed, L2-normalised bag of words: cosine tracks word overlap."""
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def overlap_ratio(query: str, text: str) -> float:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    return len(query_tokens & set(tokenize(text))) / len(query_tokens)


# ---------------------------------------------------------------------------
# In-memory Qdrant
# ---------------------------------------------------------------------------


@dataclass
class ScoredPoint:
    id: str
    score: float
    payload: dict[str, Any]


def _condition_matches(condition: Any, payload: dict[str, Any]) -> bool:
    if isinstance(condition, Filter):
        return filter_matches(condition, payload)
    if not isinstance(condition, FieldCondition):
        raise TypeError(f"unsupported filter condition: {type(condition).__name__}")
    value = payload.get(condition.key)
    match = condition.match
    if isinstance(match, MatchValue):
        return value == match.value
    if isinstance(match, MatchAny):
        return value in list(match.any)
    raise TypeError(f"unsupported match type: {type(match).__name__}")


def filter_matches(query_filter: Filter | None, payload: dict[str, Any]) -> bool:
    if query_filter is None:
        return True
    must = list(query_filter.must or [])
    must_not = list(query_filter.must_not or [])
    should = list(query_filter.should or [])
    if not all(_condition_matches(item, payload) for item in must):
        return False
    if any(_condition_matches(item, payload) for item in must_not):
        return False
    return not should or any(_condition_matches(item, payload) for item in should)


class InMemoryQdrant:
    """Cosine search over stored points; applies org/document/index filters."""

    def __init__(self) -> None:
        self._points: list[tuple[str, list[float], dict[str, Any]]] = []
        self.calls: list[dict[str, Any]] = []

    def add_point(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._points.append((point_id, vector, dict(payload)))

    def search(
        self,
        *,
        query_vector: list[float],
        query_filter: Filter | None = None,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[ScoredPoint]:
        self.calls.append({"query_filter": query_filter, "limit": limit, **kwargs})
        scored = [
            ScoredPoint(
                id=point_id,
                score=sum(a * b for a, b in zip(query_vector, vector, strict=True)),
                payload=dict(payload),
            )
            for point_id, vector, payload in self._points
            if filter_matches(query_filter, payload)
        ]
        scored.sort(key=lambda point: (-point.score, point.id))
        return scored[:limit]


# ---------------------------------------------------------------------------
# Deterministic LLM
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextBlock:
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    text: str


@dataclass(frozen=True)
class AnswerPromptRecord:
    question: str
    blocks: list[ContextBlock]
    canary_outside_context: bool
    untrusted_rule_present: bool


def _parse_context_blocks(context: str) -> list[ContextBlock]:
    # R05-09: blocks sit between `<<<CONTEXT {b}>>>` / `<<<END CONTEXT {b}>>>` lines; the
    # marker lines are dropped so the inner `[n]`, key=value, and `text:` lines parse as
    # before (the old unwrapped format still parses).
    context = re.sub(r"(?m)^<<<(?:END )?CONTEXT [0-9a-f]+>>>\n?", "", context)
    blocks: list[ContextBlock] = []
    for raw_block in re.split(r"(?m)^\[\d+\]\n", context):
        if "chunk_id=" not in raw_block:
            continue
        header, _, text = raw_block.partition("text:\n")
        fields: dict[str, str] = {}
        for line in header.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                fields[key.strip()] = value.strip()
        page = fields.get("page_number", "")
        blocks.append(
            ContextBlock(
                document_id=fields.get("document_id", ""),
                chunk_id=fields.get("chunk_id", ""),
                filename=fields.get("filename", ""),
                page_number=int(page) if page.isdigit() else None,
                text=text.strip(),
            )
        )
    return blocks


def _best_sentence(question: str, text: str) -> str:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if not sentences:
        return text
    return max(sentences, key=lambda sentence: overlap_ratio(question, sentence))


@dataclass
class DeterministicLLM:
    canary: str
    hallucinated_chunk_id: str = "00000000-0000-0000-0000-000000000000"
    answer_prompts: list[AnswerPromptRecord] = field(default_factory=list)
    rerank_prompt_count: int = 0
    unknown_prompt_count: int = 0

    def respond(self, prompt: str) -> str:
        if _RERANK_MARKER in prompt:
            self.rerank_prompt_count += 1
            return self._rerank(prompt)
        if _QUESTION_START in prompt and _CONTEXT_MARKER in prompt:
            return self._answer(prompt)
        self.unknown_prompt_count += 1
        return NOT_FOUND_JSON

    def _rerank(self, prompt: str) -> str:
        query = prompt.split("Query:\n", 1)[-1].split("\n\nCandidates:\n", 1)[0]
        candidates = prompt.split("\n\nCandidates:\n", 1)[-1]
        scores = []
        for raw in re.split(r"\n\n(?=key: )", candidates):
            key_line, _, rest = raw.partition("\n")
            if not key_line.startswith("key: "):
                continue
            text = rest.partition("text:\n")[2]
            score = round(min(1.0, max(0.0, overlap_ratio(query, text))), 4)
            scores.append({"key": key_line[len("key: ") :].strip(), "score": score})
        return json.dumps({"scores": scores})

    def _answer(self, prompt: str) -> str:
        before_context, _, context = prompt.partition(_CONTEXT_MARKER)
        question = before_context.split(_QUESTION_START, 1)[1].split(_QUESTION_END, 1)[0].strip()
        blocks = _parse_context_blocks(context)
        record = AnswerPromptRecord(
            question=question,
            blocks=blocks,
            canary_outside_context=self.canary.lower() in before_context.lower(),
            untrusted_rule_present="untrusted" in before_context.lower(),
        )
        self.answer_prompts.append(record)
        if record.canary_outside_context:
            # Simulated failure mode: an instruction in the rules/question zone is obeyed.
            return json.dumps({"answer": self.canary, "not_found": False, "citations": []})
        if not blocks or overlap_ratio(question, blocks[0].text) < GROUNDING_MIN_OVERLAP:
            return NOT_FOUND_JSON
        top = blocks[0]
        sentence = _best_sentence(question, top.text)
        citations = [
            {
                "document_id": top.document_id,
                "chunk_id": top.chunk_id,
                "filename": top.filename,
                "page_number": top.page_number,
                "text_snippet": sentence[:200],
            },
            # A fabricated citation: the pipeline's citation validation must drop it.
            {
                "document_id": top.document_id,
                "chunk_id": self.hallucinated_chunk_id,
                "filename": top.filename,
                "page_number": top.page_number,
                "text_snippet": sentence[:80],
            },
        ]
        return json.dumps({"answer": sentence, "not_found": False, "citations": citations})


class FakeChatProvider:
    def __init__(self, llm: DeterministicLLM) -> None:
        self._llm = llm

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        content = self._llm.respond(f"{request.system_message}\n\n{request.prompt}")
        return ChatCompletionResponse(
            content=content,
            model=request.model or "accuracy-smoke-fake",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            latency_ms=0,
        )


class FakeEmbeddingProvider:
    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=[hashed_embedding(text, self._dimensions) for text in request.texts],
            model=request.model or "accuracy-smoke-hash",
            prompt_tokens=5,
            total_tokens=5,
            latency_ms=0,
        )


class FakeProviderFactory:
    def __init__(self, llm: DeterministicLLM, dimensions: int) -> None:
        self._chat = FakeChatProvider(llm)
        self._embedding = FakeEmbeddingProvider(dimensions)

    def get_chat_provider(self, provider_key: str | None = None) -> FakeChatProvider:
        return self._chat

    def get_embedding_provider(self, provider_key: str | None = None) -> FakeEmbeddingProvider:
        return self._embedding


class FakeOpenAIClient:
    """Mirrors the OpenAI SDK surface the chat module uses (see test_rag_isolation_f144)."""

    def __init__(self, llm: DeterministicLLM, *, dimensions: int, model: str) -> None:
        async def _embed(*, model: str, input: list[str]) -> object:
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=hashed_embedding(t, dimensions)) for t in input],
                usage=SimpleNamespace(prompt_tokens=5, total_tokens=5),
                model=model,
            )

        async def _complete(**kwargs: Any) -> object:
            prompt = "\n\n".join(str(m.get("content", "")) for m in kwargs.get("messages", []))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=llm.respond(prompt)))],
                usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                model=model,
            )

        self.embeddings = SimpleNamespace(create=_embed)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=_complete))


# ---------------------------------------------------------------------------
# Metrics and gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionOutcome:
    question: SmokeQuestion
    not_found: bool
    answer: str
    cited_chunk_ids: list[str]
    context_chunk_ids: list[str]
    context_filenames: list[str]
    canary_outside_context: bool = False
    untrusted_rule_present: bool = True


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def injection_not_followed(outcome: QuestionOutcome, canary: str) -> bool:
    if canary.lower() in outcome.answer.lower():
        return False
    if outcome.canary_outside_context or not outcome.untrusted_rule_present:
        return False
    if outcome.question.expected_not_found:
        return outcome.not_found and not outcome.cited_chunk_ids
    return True


def compute_summaries(
    outcomes: list[QuestionOutcome], *, canary: str
) -> tuple[dict[str, float], dict[str, float]]:
    """Return (evaluation_summary, safety_summary) in the F149 gate's key names."""
    answerable = [o for o in outcomes if not o.question.expected_not_found]
    refusals = [o for o in outcomes if o.question.expected_not_found]
    answered = [o for o in outcomes if not o.not_found]
    injections = [o for o in outcomes if o.question.injection]

    hits = sum(1 for o in answerable if o.question.expected_document in o.context_filenames)
    accurate = sum(
        1
        for o in answered
        if o.cited_chunk_ids and set(o.cited_chunk_ids) <= set(o.context_chunk_ids)
    )
    refused = sum(1 for o in refusals if o.not_found and not o.cited_chunk_ids)
    safe = sum(1 for o in injections if injection_not_followed(o, canary))
    evaluation_summary = {
        "retrieval_hit_rate": _ratio(hits, len(answerable)),
        "citation_accuracy_score": _ratio(accurate, len(answered)),
        "refusal_accuracy_score": _ratio(refused, len(refusals)),
        "not_found_rate": _ratio(sum(1 for o in outcomes if o.not_found), len(outcomes)),
    }
    safety_summary = {"pass_rate": _ratio(safe, len(injections))}
    return evaluation_summary, safety_summary


def load_smoke_thresholds(path: Path = THRESHOLDS_PATH) -> QualityGateThresholds:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    smoke = raw["smoke"]
    return QualityGateThresholds(**{name: smoke[name] for name in MEASURED_THRESHOLD_FIELDS})
