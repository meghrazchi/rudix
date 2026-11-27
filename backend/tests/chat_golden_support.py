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
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid5

import pytest
from chat_golden_providers import RecordingChatProvider
from chat_golden_state import persisted_state
from fastapi import HTTPException
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
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.domains.documents.repositories.documents import DocumentRepository
from app.interfaces.http import chat as chat_api
from app.models.document import DocumentChunk
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.quotas import OrgQuotaUsage
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


async def ask_http_direct(db_session: AsyncSession, world: GoldenWorld) -> dict[str, Any]:
    """Call ``query_chat`` in-process, the way the bot service does.

    Same transcript as ``ask_http``; it exists because code awaited inside the ASGI request
    is not traced by coverage in this test setup, so the pipeline lines are measured here.
    """
    request = SimpleNamespace(
        state=SimpleNamespace(request_id="6a1f7c2e-0d4b-4e8a-9c3f-5b2d1e0a9f87"), headers={}
    )
    principal = chat_api.AuthenticatedPrincipal(
        user_id=str(world.user.id),
        organization_id=str(world.organization.id),
        email=world.user.email,
        roles=[world.role.value],
        auth_provider="app",
    )
    try:
        response = await chat_api.query_chat(
            request=request,  # type: ignore[arg-type]
            payload=ChatQueryRequest.model_validate(world.payload),
            principal=principal,
            _=None,
            db_session=db_session,
        )
    except HTTPException as exc:
        return {"status_code": exc.status_code, "error": exc.detail}
    body = json.loads(response.model_dump_json())
    body.pop("trust_metadata", None)
    return {"status_code": 200, "response": body}


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
    elif transport == "http_direct":
        outcome = await ask_http_direct(db_session, world)
    else:
        outcome = await ask_ws(db_session, monkeypatch, world)
    if transport != "ws" and outcome["status_code"] != 200:
        # The test shares one session with the request; ``get_db_session`` would close it
        # after a refused request, which rolls back anything left uncommitted (R05-02).
        await db_session.rollback()
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


def golden_target(transport: str, pipeline_v2: bool) -> tuple[str, bool]:
    """Fixture transport and whether ``CHAT_GOLDEN_UPDATE=1`` may rewrite it.

    HTTP fixtures are recorded by the legacy body and reproduced by the pipeline. Since S2
    the WebSocket runs every pipeline stage: ``ws`` fixtures are recorded by the pipeline
    run, and ``ws_legacy`` keeps the pre-pipeline WebSocket transcripts (never rewritten)
    for the legacy body that stays reachable with ``CHAT_PIPELINE_V2=false`` until S3.
    """
    if transport == "ws":
        return ("ws", True) if pipeline_v2 else ("ws_legacy", False)
    if transport == "http_direct":
        return "http", False
    return transport, not pipeline_v2


def fixture_path(scenario: str, transport: str) -> Path:
    return FIXTURE_DIR / f"{scenario}.{transport}.json"


def _dump(transcript: dict[str, Any]) -> str:
    return json.dumps(transcript, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def assert_matches_golden(
    scenario: str, transport: str, transcript: dict[str, Any], *, allow_update: bool = True
) -> None:
    path = fixture_path(scenario, transport)
    rendered = _dump(transcript)
    if allow_update and os.environ.get(UPDATE_ENV) == "1":
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
