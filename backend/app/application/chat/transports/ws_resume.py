"""``chat.resume`` on ``/chat/ws`` (R05-13, plan contract 4.2.7).

``{"command": "chat.resume", "payload": {"message_id": "<uuid>", "last_stream_sequence":
<int>}}`` on a new connection (authenticated like any other, for example with a fresh
ticket). The resume key is built from the principal of *this* connection, so only the user
who started the run, in the same organisation, can read its buffer.

1. The buffer exists: ``chat.resumed`` (``{"message_id", "replayed"}``), the buffered events
   with a higher ``stream_sequence`` in order, then the live events until a terminal one.
2. The buffer is gone but the assistant message is stored in a chat session of this
   organisation and user: ``chat.resumed`` with ``replayed: 0`` and one ``chat.completed``
   rebuilt from the stored message (``payload.rebuilt = true``; the response carries the
   stored answer, confidence, citations, and trust metadata, not the per-request debug).
3. Otherwise, a failing or missing Redis, or a buffer that expires while tailing:
   ``chat.error`` with ``resume_unavailable``.

Outcomes are counted in ``rudix_chat_ws_resume_total{outcome}``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.application.chat.message_citations import load_message_citations
from app.application.chat.pipeline.deps import SessionFactory, default_deps
from app.application.chat.pipeline.request_helpers import _principal_user_and_org
from app.application.chat.transports.resume_buffer import replay_buffer, resume_key
from app.application.chat.transports.ws import (
    WebSocketLike,
    WsRunHandle,
    WsSequence,
    current_ws_run,
    start_ws_run,
    ws_send,
)
from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.logging import log_query_event
from app.core.metrics import CHAT_WS_RESUME_TOTAL
from app.db.tenant_context import bind_pipeline_session
from app.domains.chat.schemas.chat_ws import ChatWSOutboundEvent
from app.domains.chat.schemas.trust_metadata import AnswerTrustMetadataResponse
from app.domains.chat.services.citation_enrichment import _with_provenance
from app.domains.chat.services.confidence_calibration import _confidence_category_from_score
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import ChatRole


def parse_resume_payload(payload: dict[str, Any] | None) -> tuple[UUID, int] | None:
    """``(message_id, last_stream_sequence)`` or ``None`` for an invalid payload."""
    data = payload or {}
    try:
        message_id = UUID(str(data.get("message_id")))
    except (TypeError, ValueError):
        return None
    last = data.get("last_stream_sequence", 0)
    if isinstance(last, bool) or not isinstance(last, int) or last < 0:
        return None
    return message_id, last


class _Sender:
    def __init__(self, websocket: WebSocketLike, sequence: WsSequence, message_id: str) -> None:
        self.websocket = websocket
        self.sequence = sequence
        self.message_id = message_id

    async def send(
        self,
        event: str,
        payload: dict[str, Any] | None = None,
        *,
        safe_error_code: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        await ws_send(
            self.websocket,
            ChatWSOutboundEvent(
                event=event,  # type: ignore[arg-type]
                message_id=self.message_id,
                conversation_id=conversation_id,
                sequence=self.sequence.next(),
                payload=payload,
                safe_error_code=safe_error_code,
            ),
        )

    async def send_text(self, data: str) -> None:
        try:
            await self.websocket.send_text(data)
        except Exception:
            pass


async def run_ws_resume(
    *,
    websocket: WebSocketLike,
    payload: dict[str, Any] | None,
    principal: AuthenticatedPrincipal,
    sequence: WsSequence,
    session_factory: SessionFactory,
) -> None:
    """Answer one ``chat.resume`` command (see the module docstring)."""
    parsed = parse_resume_payload(payload)
    if parsed is None:
        await ws_send(
            websocket,
            ChatWSOutboundEvent(
                event="chat.error", sequence=sequence.next(), safe_error_code="invalid_request"
            ),
        )
        return
    message_id, last = parsed
    user_id, organization_id = _principal_user_and_org(principal)
    sender = _Sender(websocket, sequence, str(message_id))
    redis = redis_module.redis_client
    if redis is None:
        await _unavailable(sender, principal, "redis_unavailable")
        return
    key = resume_key(organization_id, user_id, message_id)
    handle = current_ws_run()
    if handle is not None:
        handle.resume_of = key

    async def on_resumed(replayed: int) -> None:
        await sender.send("chat.resumed", {"message_id": str(message_id), "replayed": replayed})

    try:
        result = await replay_buffer(
            redis,
            key,
            last_stream_sequence=last,
            sequence=sequence,
            send_text=sender.send_text,
            on_resumed=on_resumed,
        )
    except Exception as exc:
        log_query_event(
            event="chat.ws.resume.redis_error",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            error=exc.__class__.__name__,
        )
        await _unavailable(sender, principal, "redis_unavailable")
        return
    if result.found:
        if result.terminal is None:
            await _unavailable(sender, principal, "unavailable")
            return
        _record(principal, "replayed", replayed=result.replayed)
        return
    response = await load_stored_answer(
        session_factory,
        message_id=message_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if response is None:
        await _unavailable(sender, principal, "unavailable")
        return
    await on_resumed(0)
    await sender.send(
        "chat.completed",
        {"response": response, "rebuilt": True},
        conversation_id=str(response["chat_session_id"]),
    )
    _record(principal, "rebuilt", replayed=0)


async def _unavailable(sender: _Sender, principal: AuthenticatedPrincipal, outcome: str) -> None:
    _record(principal, outcome)
    await sender.send("chat.error", safe_error_code="resume_unavailable")


def _record(principal: AuthenticatedPrincipal, outcome: str, *, replayed: int = 0) -> None:
    CHAT_WS_RESUME_TOTAL.labels(outcome=outcome).inc()
    log_query_event(
        event="chat.ws.resume",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        outcome=outcome,
        replayed=replayed,
    )


async def load_stored_answer(
    session_factory: SessionFactory,
    *,
    message_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    decorate: Callable[..., Any] | None = _with_provenance,
) -> dict[str, Any] | None:
    """The stored assistant message as a ``chat.completed`` response, or ``None`` when it
    does not exist in a chat session of this organisation and user."""
    async with session_factory() as db_session:
        await bind_pipeline_session(db_session, organization_id)
        message = await db_session.scalar(
            select(ChatMessage)
            .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
            .where(
                ChatMessage.id == message_id,
                ChatMessage.role == ChatRole.assistant.value,
                ChatSession.organization_id == organization_id,
                ChatSession.user_id == user_id,
            )
        )
        if message is None:
            return None
        citations = await load_message_citations(
            db_session,
            messages=[message],
            organization_id=organization_id,
            decorate=decorate,
            provenance_service=default_deps.source_provenance_service,
        )
        trust = (
            AnswerTrustMetadataResponse.model_validate(message.trust_metadata_json)
            if message.trust_metadata_json is not None
            else None
        )
        return {
            "chat_session_id": str(message.chat_session_id),
            "message_id": str(message.id),
            "answer": message.content,
            "confidence_score": message.confidence_score,
            "confidence_category": _confidence_category_from_score(message.confidence_score),
            "citations": [json.loads(c.model_dump_json()) for c in citations.get(message.id, [])],
            "trust_metadata": json.loads(trust.model_dump_json()) if trust is not None else None,
            "created_at": message.created_at.isoformat(),
        }


def start_ws_resume(
    websocket: WebSocketLike,
    payload: dict[str, Any] | None,
    principal: AuthenticatedPrincipal,
    sequence: WsSequence,
    session_factory: SessionFactory,
) -> tuple[asyncio.Task[None], WsRunHandle]:
    """Start ``run_ws_resume`` as the connection's active task."""
    handle = WsRunHandle()
    task = start_ws_run(
        run_ws_resume(
            websocket=websocket,
            payload=payload,
            principal=principal,
            sequence=sequence,
            session_factory=session_factory,
        ),
        handle,
    )
    return task, handle
