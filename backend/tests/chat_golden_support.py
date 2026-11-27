"""Golden transcript support for the chat pipeline (R05-01).

The goldens are recorded through the chat transports with fake providers and compared on
every run. ``CHAT_GOLDEN_UPDATE=1`` rewrites the fixtures instead of comparing them.

A transcript holds the response or safe error, stored trust metadata, persisted rows, the
``questions`` quota delta, provider calls (kind, prompt sha256) and, for the WebSocket, the
ordered events. UUIDs become labels by first appearance; timestamps, latencies, request ids
and ``sequence`` are dropped; floats are rounded to six decimal places.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pytest
from chat_golden_providers import RecordingChatProvider
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import (
    FakeQdrantClient,
    FakeQdrantResult,
    _auth_headers,
    _FakeWebSocket,
)
from test_chat_transport_parity import _SessionLocalOverride

from app.auth.token_codec import create_app_access_token
from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.documents.repositories.documents import DocumentRepository
from app.interfaces.http import chat as chat_api
from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.document import DocumentChunk
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.quotas import OrgQuotaUsage
from app.models.usage import UsageEvent
from app.models.user import User

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "chat_golden"
UPDATE_ENV = "CHAT_GOLDEN_UPDATE"
_GOLDEN_NAMESPACE = UUID("6f1d3a52-6c4e-4d61-9a43-5a1d0c2b7e10")

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# ConflictDetectionService builds conflicting_document_ids from a set, so their order follows
# the string hash seed of the process. Those lists (and the prompt line) are compared sorted.
_SET_ORDERED_KEY_SUFFIX = "conflicting_document_ids"
_CONFLICTING_LINE_RE = re.compile(r"^(- conflicting_document_ids: )(.+)$", re.MULTILINE)
_DROPPED_KEYS = frozenset(
    {"request_id", "sequence", "timestamp", "duration_ms", "trace_id", "conversation_id"}
)

# ---------------------------------------------------------------------------
# Scenario world
# ---------------------------------------------------------------------------


@dataclass
class GoldenWorld:
    user: User
    organization: Organization
    role: OrganizationRole
    provider: RecordingChatProvider
    payload: dict[str, Any]
    labels: dict[str, str] = field(default_factory=dict)

    def label(self, value: object, name: str) -> None:
        self.labels[str(value)] = f"<{name}>"


@dataclass(frozen=True)
class SeedDoc:
    key: str
    text: str
    score: float
    trust_status: str | None = None


async def seed_documents(
    db_session: AsyncSession,
    world: GoldenWorld,
    docs: list[SeedDoc],
) -> dict[str, tuple[UUID, UUID]]:
    """Seed one chunk per document and point the fake Qdrant client at them."""
    seeded: dict[str, tuple[UUID, UUID]] = {}
    results: list[FakeQdrantResult] = []
    repository = DocumentRepository()
    for doc in docs:
        # Fixed ids keep orderings that sort by id (conflict groups, id lists) stable.
        document_id = uuid5(_GOLDEN_NAMESPACE, f"document:{doc.key}")
        chunk_id = uuid5(_GOLDEN_NAMESPACE, f"chunk:{doc.key}")
        document = await repository.create_document(
            db_session,
            document_id=document_id,
            organization_id=world.organization.id,
            uploaded_by_user_id=world.user.id,
            filename=f"{doc.key}.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key=f"seed/{doc.key}.pdf",
            status="indexed",
        )
        chunk = DocumentChunk(
            id=chunk_id,
            document_id=document_id,
            page_number=1,
            chunk_index=0,
            text=doc.text,
            token_count=50,
            embedding_model=settings.openai_embedding_model,
            index_version=settings.document_index_version,
            qdrant_point_id=f"{document_id}:{settings.document_index_version}:0",
        )
        db_session.add(chunk)
        await db_session.commit()
        if doc.trust_status is not None:
            document.trust_status = doc.trust_status
            db_session.add(document)
            await db_session.commit()
        world.label(document_id, f"doc:{doc.key}")
        world.label(chunk_id, f"chunk:{doc.key}")
        seeded[doc.key] = (document_id, chunk_id)
        results.append(
            FakeQdrantResult(
                score=doc.score,
                payload={
                    "organization_id": str(world.organization.id),
                    "document_id": str(document_id),
                    "chunk_id": str(chunk_id),
                    "filename": f"{doc.key}.pdf",
                    "page_number": 1,
                    "text": doc.text,
                },
            )
        )
    qdrant_module.qdrant_client = FakeQdrantClient(results)
    return seeded


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


async def _question_usage(db_session: AsyncSession, organization_id: UUID) -> int:
    value = await db_session.scalar(
        select(OrgQuotaUsage.current_value).where(
            OrgQuotaUsage.organization_id == organization_id,
            OrgQuotaUsage.quota_type == "questions",
        )
    )
    return int(value or 0)


async def ask_http(client: AsyncClient, world: GoldenWorld) -> dict[str, Any]:
    token = create_app_access_token(
        subject=world.user.external_auth_id,
        organization_id=str(world.organization.id),
        expires_in_seconds=600,
    )
    response = await client.post(
        "/api/v1/chat",
        headers=_auth_headers(token=token, organization_id=str(world.organization.id)),
        json=world.payload,
    )
    body = response.json()
    if response.status_code != 200:
        return {"status_code": response.status_code, "error": body.get("detail")}
    body.pop("trust_metadata", None)
    return {"status_code": response.status_code, "response": body}


def _collapse_ws_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collapsed: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") or {}
        if event["event"] == "generation.delta":
            text = str(payload.get("text", ""))
            if collapsed and collapsed[-1]["event"] == "generation.delta":
                collapsed[-1]["text"] += text
            else:
                collapsed.append({"event": "generation.delta", "text": text})
            continue
        record: dict[str, Any] = {
            "event": event["event"],
            "payload_keys": sorted(payload),
        }
        if event["event"] == "activity.step.update":
            record["step_key"] = payload.get("step_key")
            record["state"] = payload.get("state")
        if event.get("safe_error_code"):
            record["safe_error_code"] = event["safe_error_code"]
        if event["event"] == "chat.error":
            record["payload"] = event.get("payload")
        collapsed.append(record)
    return collapsed


async def ask_ws(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, world: GoldenWorld
) -> dict[str, Any]:
    monkeypatch.setattr(chat_api, "SessionLocal", _SessionLocalOverride(db_session))
    websocket = _FakeWebSocket()
    principal = chat_api.AuthenticatedPrincipal(
        user_id=str(world.user.id),
        organization_id=str(world.organization.id),
        email=world.user.email,
        roles=[world.role.value],
        auth_provider="app",
    )
    payload = {"chat_session_id": None, **world.payload}
    await chat_api._run_ws_chat_pipeline(
        websocket=websocket,  # type: ignore[arg-type]
        payload=payload,
        principal=principal,
        request_id="ws-golden",
        sequence_start=0,
    )
    events = [json.loads(text) for text in websocket.sent_texts]
    result: dict[str, Any] = {"events": _collapse_ws_events(events)}
    last = events[-1] if events else {}
    if last.get("event") == "chat.completed":
        response = dict(last["payload"]["response"])
        response.pop("trust_metadata", None)
        result["response"] = response
    else:
        result["error"] = {
            "safe_error_code": last.get("safe_error_code"),
            "payload": last.get("payload"),
        }
    return result


# ---------------------------------------------------------------------------
# Persisted state
# ---------------------------------------------------------------------------


def _decimal(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    return value


async def persisted_state(db_session: AsyncSession, organization_id: UUID) -> dict[str, Any]:
    db_session.expire_all()
    sessions = list(
        (
            await db_session.execute(
                select(ChatSession)
                .where(ChatSession.organization_id == organization_id)
                .order_by(ChatSession.created_at)
            )
        )
        .scalars()
        .all()
    )
    session_ids = [row.id for row in sessions]
    messages: list[ChatMessage] = []
    if session_ids:
        messages = list(
            (
                await db_session.execute(
                    select(ChatMessage).where(ChatMessage.chat_session_id.in_(session_ids))
                )
            )
            .scalars()
            .all()
        )
    messages.sort(key=lambda m: (m.created_at, 0 if m.role == "user" else 1))
    message_ids = [row.id for row in messages]
    citations: list[Citation] = []
    if message_ids:
        citations = list(
            (
                await db_session.execute(
                    select(Citation).where(Citation.chat_message_id.in_(message_ids))
                )
            )
            .scalars()
            .all()
        )
    order = {message_id: index for index, message_id in enumerate(message_ids)}
    citations.sort(key=lambda c: (order[c.chat_message_id], c.created_at, c.text_snippet))
    usage = list(
        (
            await db_session.execute(
                select(UsageEvent)
                .where(UsageEvent.organization_id == organization_id)
                .order_by(UsageEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "chat_sessions": [{"id": str(row.id), "title": row.title} for row in sessions],
        "chat_messages": [
            {
                "id": str(row.id),
                "chat_session_id": str(row.chat_session_id),
                "role": row.role,
                "content": row.content,
                "confidence_score": _decimal(row.confidence_score),
                "model_name": row.model_name,
                "token_input_count": row.token_input_count,
                "token_output_count": row.token_output_count,
                "cost_usd": _decimal(row.cost_usd),
                "prompt_template_version_id": (
                    str(row.prompt_template_version_id)
                    if row.prompt_template_version_id is not None
                    else None
                ),
                "trust_metadata_json": row.trust_metadata_json,
            }
            for row in messages
        ],
        "citations": [
            {
                "chat_message_id": str(row.chat_message_id),
                "document_id": str(row.document_id),
                "chunk_id": str(row.chunk_id),
                "page_number": row.page_number,
                "text_snippet": row.text_snippet,
                "similarity_score": _decimal(row.similarity_score),
                "rerank_score": _decimal(row.rerank_score),
            }
            for row in citations
        ],
        "usage_events": [
            {
                "event_type": row.event_type,
                "model_name": row.model_name,
                "provider_key": row.provider_key,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost_usd": _decimal(row.cost_usd),
                "metadata": row.metadata_json,
            }
            for row in usage
        ],
    }


# ---------------------------------------------------------------------------
# Recording and normalisation
# ---------------------------------------------------------------------------


async def record_transcript(
    transport: str,
    *,
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    world: GoldenWorld,
) -> dict[str, Any]:
    organization_id = world.organization.id
    before = await _question_usage(db_session, organization_id)
    if transport == "http":
        outcome = await ask_http(client, world)
    else:
        outcome = await ask_ws(db_session, monkeypatch, world)
    persisted = await persisted_state(db_session, organization_id)
    after = await _question_usage(db_session, organization_id)
    raw: dict[str, Any] = {
        **outcome,
        "questions_quota_delta": after - before,
        **persisted,
        "provider_calls": [
            {"kind": kind, "prompt": request.prompt} for kind, request in world.provider.calls
        ],
    }
    return normalise_transcript(raw, labels=world.labels)


class _Normaliser:
    def __init__(self, labels: dict[str, str]) -> None:
        self._labels = {key.lower(): value for key, value in labels.items()}
        self._counter = 0

    def _label(self, match: re.Match[str]) -> str:
        key = match.group(0).lower()
        if key not in self._labels:
            self._counter += 1
            self._labels[key] = f"<uuid:{self._counter}>"
        return self._labels[key]

    def text(self, value: str) -> str:
        return _UUID_RE.sub(self._label, value)

    def walk(self, value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if _is_dropped_key(str(key)):
                    continue
                walked = self.walk(item)
                if str(key).endswith(_SET_ORDERED_KEY_SUFFIX) and isinstance(walked, list):
                    walked = sorted(walked, key=str)
                result[self.text(str(key))] = walked
            return result
        if isinstance(value, list | tuple):
            return [self.walk(item) for item in value]
        if isinstance(value, bool) or value is None or isinstance(value, int):
            return value
        if isinstance(value, float | Decimal):
            return round(float(value), 6)
        if isinstance(value, UUID):
            return self.text(str(value))
        if isinstance(value, str):
            return self.text(value)
        return self.text(str(value))


def _is_dropped_key(key: str) -> bool:
    return (
        key in _DROPPED_KEYS
        or key.endswith("_at")
        or "latenc" in key
        or key.endswith("_ms")
        or key.endswith("_seconds")
    )


def normalise_transcript(raw: dict[str, Any], *, labels: dict[str, str]) -> dict[str, Any]:
    normaliser = _Normaliser(labels)
    calls = raw.pop("provider_calls")
    result = normaliser.walk(raw)
    result["provider_call_count"] = len(calls)
    result["provider_calls"] = [
        {
            "kind": call["kind"],
            "prompt_sha256": hashlib.sha256(
                normalise_prompt(normaliser.text(call["prompt"])).encode("utf-8")
            ).hexdigest(),
        }
        for call in calls
    ]
    return result


def normalise_prompt(prompt: str) -> str:
    """Prompt normalisation beyond UUID labels (contract 4.2.4; B1 adds its boundary token)."""
    return _CONFLICTING_LINE_RE.sub(
        lambda match: match.group(1) + ", ".join(sorted(match.group(2).split(", "))), prompt
    )


# ---------------------------------------------------------------------------
# Fixture comparison
# ---------------------------------------------------------------------------


def fixture_path(scenario: str, transport: str) -> Path:
    return FIXTURE_DIR / f"{scenario}.{transport}.json"


def _dump(transcript: dict[str, Any]) -> str:
    return json.dumps(transcript, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def assert_matches_golden(scenario: str, transport: str, transcript: dict[str, Any]) -> None:
    path = fixture_path(scenario, transport)
    rendered = _dump(transcript)
    if os.environ.get(UPDATE_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(f"missing golden {path.name}; record it with {UPDATE_ENV}=1")
    expected = path.read_text(encoding="utf-8")
    if expected != rendered:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=f"golden/{path.name}",
                tofile="recorded",
                n=3,
            )
        )
        pytest.fail(f"golden transcript {path.name} differs:\n{diff}", pytrace=False)
