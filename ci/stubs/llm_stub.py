#!/usr/bin/env python3
"""Deterministic OpenAI-compatible LLM and embedding stub (test only).

Used by the integration e2e suite (R03-04) and the load harness (R03-09). Standard library
only. It is never a production provider: answers are built mechanically from the prompt.

Endpoints: GET /health, GET /v1/models, POST /v1/embeddings, POST /v1/chat/completions.

Environment:
    STUB_LLM_PORT               listen port (default 8080)
    STUB_LLM_LATENCY_MS         fixed delay before every /v1 response (default 0)
    STUB_LLM_LATENCY_JITTER_MS  extra uniform random delay, 0..N ms (default 0)
    STUB_EMBEDDING_DIM          embedding dimension (default 1536 = QDRANT_VECTOR_SIZE)

Request bodies and prompts are never logged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import re
import struct
import sys
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_NOT_FOUND_ANSWER = "I could not find this information in the uploaded documents."
CHAT_MODEL = "stub-chat"
EMBEDDING_MODEL = "stub-embedding"
MAX_BODY_BYTES = 16 * 1024 * 1024
SNIPPET_CHARS = 160

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ALLOWED_RE = re.compile(r"Allowed citation chunk_ids:\n([^\n]*)")
_NOT_FOUND_RE = re.compile(r"answer exactly: ([^\n]+)")
_BLOCK_START_RE = re.compile(r"^\[\d+\]\ndocument_id=", re.M)
_RERANK_KEY_RE = re.compile(r"^key: (.+)\noriginal_rank: ", re.M)
_CONTEXT_MARKER = "<<QUESTION_END>>\n\nContext blocks:\n"


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return max(0, int(raw)) if raw else default
    except ValueError:
        return default


def simulate_latency(
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[float, float], float] = random.uniform,
) -> float:
    """Sleep STUB_LLM_LATENCY_MS plus up to STUB_LLM_LATENCY_JITTER_MS; return seconds."""
    base_ms = env_int("STUB_LLM_LATENCY_MS", 0)
    jitter_ms = env_int("STUB_LLM_LATENCY_JITTER_MS", 0)
    delay_ms = base_ms + (rng(0.0, float(jitter_ms)) if jitter_ms else 0.0)
    seconds = delay_ms / 1000.0
    if seconds > 0:
        sleep(seconds)
    return seconds


def embed_text(text: str, dim: int) -> list[float]:
    """Feature-hash lowercase word tokens into a signed, L2-normalised vector."""
    vector = [0.0] * dim
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        vector[value % dim] += 1.0 if (value >> 63) & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [item / norm for item in vector]


def prompt_kind(text: str) -> str:
    if "reranking retrieved document chunks" in text or "document retrieval reranker" in text:
        return "rerank"
    if "keys: answer, not_found, citations" in text:
        return "answer"
    return "other"


def _first_block(context: str) -> dict[str, str] | None:
    starts = [match.start() for match in _BLOCK_START_RE.finditer(context)]
    if not starts:
        return None
    end = starts[1] if len(starts) > 1 else len(context)
    block = context[starts[0] : end]
    fields: dict[str, str] = {}
    header, _, text = block.partition("\ntext:\n")
    for line in header.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    fields["text"] = text.strip()
    return fields


def answer_payload(prompt: str) -> dict[str, Any]:
    """Grounded answer JSON citing the first allowed chunk, or the not-found answer."""
    not_found_match = _NOT_FOUND_RE.search(prompt)
    not_found_answer = (
        not_found_match.group(1).strip() if not_found_match else DEFAULT_NOT_FOUND_ANSWER
    )
    allowed_match = _ALLOWED_RE.search(prompt)
    allowed = (
        {item.strip() for item in allowed_match.group(1).split(",") if item.strip()}
        if allowed_match
        else set()
    )
    allowed.discard("<none>")
    marker = _CONTEXT_MARKER if _CONTEXT_MARKER in prompt else "Context blocks:\n"
    _, _, context = prompt.partition(marker)
    block = _first_block(context) if allowed else None
    if block is None or block.get("chunk_id") not in allowed:
        return {"answer": not_found_answer, "not_found": True, "citations": []}
    snippet = " ".join(block["text"].split())[:SNIPPET_CHARS].strip()
    page_raw = block.get("page_number", "")
    citation: dict[str, Any] = {
        "document_id": block.get("document_id", ""),
        "chunk_id": block["chunk_id"],
        "filename": block.get("filename", ""),
        "page_number": int(page_raw) if page_raw.isdigit() else None,
        "text_snippet": snippet,
    }
    answer = f'According to {citation["filename"]}: "{snippet}"'
    return {"answer": answer, "not_found": False, "citations": [citation]}


def rerank_payload(prompt: str) -> dict[str, Any]:
    """Identity ranking: candidates keep their input order with descending scores."""
    keys = [key.strip() for key in _RERANK_KEY_RE.findall(prompt)]
    step = 0.5 / max(len(keys), 1)
    return {
        "scores": [{"key": key, "score": round(1.0 - i * step, 4)} for i, key in enumerate(keys)]
    }


def completion_content(messages: list[dict[str, Any]], json_mode: bool) -> str:
    text = "\n".join(str(message.get("content") or "") for message in messages)
    kind = prompt_kind(text)
    if kind == "answer":
        return json.dumps(answer_payload(text))
    if kind == "rerank":
        return json.dumps(rerank_payload(text))
    return "{}" if json_mode else "OK"


def _count_tokens(text: str) -> int:
    return len(text.split())


def chat_completion(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages") or []
    response_format = body.get("response_format") or {}
    json_mode = isinstance(response_format, dict) and response_format.get("type") == "json_object"
    content = completion_content(messages, json_mode)
    prompt_tokens = sum(_count_tokens(str(m.get("content") or "")) for m in messages)
    completion_tokens = _count_tokens(content)
    return {
        "id": "chatcmpl-stub-" + hashlib.sha1(content.encode("utf-8")).hexdigest()[:12],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": str(body.get("model") or CHAT_MODEL),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def stream_events(completion: dict[str, Any]) -> list[str]:
    """SSE `data:` lines for a `stream: true` request, ending with [DONE]."""
    base = {k: completion[k] for k in ("id", "created", "model")}
    content = completion["choices"][0]["message"]["content"]
    deltas: list[dict[str, Any]] = [
        {"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None},
        {"index": 0, "delta": {"content": content}, "finish_reason": None},
        {"index": 0, "delta": {}, "finish_reason": "stop"},
    ]
    events = [
        json.dumps({**base, "object": "chat.completion.chunk", "choices": [delta]})
        for delta in deltas
    ]
    return [f"data: {event}\n\n" for event in events] + ["data: [DONE]\n\n"]


def embeddings(body: dict[str, Any]) -> dict[str, Any]:
    raw_input = body.get("input", "")
    texts = [str(item) for item in raw_input] if isinstance(raw_input, list) else [str(raw_input)]
    requested_dim = body.get("dimensions")
    dim = requested_dim if isinstance(requested_dim, int) and requested_dim > 0 else None
    dim = dim or env_int("STUB_EMBEDDING_DIM", 1536) or 1536
    as_base64 = body.get("encoding_format") == "base64"
    data: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        vector = embed_text(text, dim)
        encoded: Any = vector
        if as_base64:
            encoded = base64.b64encode(struct.pack(f"<{dim}f", *vector)).decode("ascii")
        data.append({"object": "embedding", "index": index, "embedding": encoded})
    tokens = sum(_count_tokens(text) for text in texts)
    return {
        "object": "list",
        "data": data,
        "model": str(body.get("model") or EMBEDDING_MODEL),
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }


class StubHandler(BaseHTTPRequestHandler):
    server_version = "RudixLLMStub/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Method, path and status only; never request bodies.
        sys.stderr.write(f"llm-stub {self.command} {self.path.split('?')[0]}\n")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": {"message": message, "type": "invalid_request_error"}})

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path == "/health":
            self._send_json(200, {"status": "ok"})
        elif path == "/v1/models":
            models = [
                {"id": m, "object": "model", "owned_by": "stub"}
                for m in (CHAT_MODEL, EMBEDDING_MODEL)
            ]
            self._send_json(200, {"object": "list", "data": models})
        else:
            self._error(404, "not found")

    def _read_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path not in ("/v1/chat/completions", "/v1/embeddings"):
            self._error(404, "not found")
            return
        body = self._read_body()
        if body is None:
            self._error(400, "request body must be a JSON object")
            return
        simulate_latency()
        if path == "/v1/embeddings":
            self._send_json(200, embeddings(body))
            return
        completion = chat_completion(body)
        if not body.get("stream"):
            self._send_json(200, completion)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in stream_events(completion):
            self.wfile.write(event.encode("utf-8"))
            self.wfile.flush()
        self.close_connection = True


def build_server(host: str = "0.0.0.0", port: int | None = None) -> ThreadingHTTPServer:
    listen_port = env_int("STUB_LLM_PORT", 8080) if port is None else port
    server = ThreadingHTTPServer((host, listen_port), StubHandler)
    server.daemon_threads = True
    return server


def main() -> None:
    server = build_server()
    sys.stderr.write(f"llm-stub listening on port {server.server_address[1]}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
