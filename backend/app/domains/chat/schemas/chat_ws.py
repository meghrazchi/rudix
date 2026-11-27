from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ChatWSCommandType = Literal["chat.start", "chat.cancel", "heartbeat.pong"]

ChatWSEventType = Literal[
    "connection.ready",
    "chat.request.received",
    "chat.scope.validated",
    "retrieval.started",
    "retrieval.completed",
    "rerank.started",
    "rerank.completed",
    "generation.started",
    "generation.delta",
    "generation.final",
    "generation.replace",
    "citation.validation.started",
    "citation.validation.completed",
    "activity.step.update",
    "chat.completed",
    "chat.cancelled",
    "chat.error",
    "heartbeat.ping",
]


# Every ``safe_error_code`` the chat WebSocket may emit. The outbound field stays
# typed ``str | None`` so an unlisted code can never raise inside the sender;
# tests/test_chat_ws_error_codes.py keeps this list in sync with chat.py.
ChatWSSafeErrorCode = Literal[
    "already_running",
    "chat_persistence_failed",
    "chat_session_not_found",
    "document_not_found",
    "generation_failed",
    "internal_error",
    "invalid_message",
    "invalid_request",
    "plan_limit_exceeded",
    "rate_limit_exceeded",
    "rate_limiter_unavailable",
    "retrieval_failed",
]


class ChatWSInboundMessage(BaseModel):
    command: ChatWSCommandType
    payload: dict[str, Any] | None = None
    request_id: str | None = None


class ChatWSOutboundEvent(BaseModel):
    event: ChatWSEventType
    request_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    sequence: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    payload: dict[str, Any] | None = None
    safe_error_code: str | None = None

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=False)


class ChatWsTicketResponse(BaseModel):
    """Single-use handshake ticket for ``/chat/ws?ticket=`` (R02-10)."""

    ticket: str
    expires_in: int
