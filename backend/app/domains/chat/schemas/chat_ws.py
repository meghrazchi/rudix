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
    "citation.validation.started",
    "citation.validation.completed",
    "activity.step.update",
    "chat.completed",
    "chat.cancelled",
    "chat.error",
    "heartbeat.ping",
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
