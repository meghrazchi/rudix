"""Typed events of the chat pipeline and the emitters that receive them (R05-01).

The pipeline emits ``ChatEvent`` objects; a transport decides what to do with them. The
WebSocket adapter (S2) forwards them, the HTTP adapter collects and ignores them.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domains.chat.schemas.chat_ws import ChatWSEventType


@dataclass(frozen=True)
class ChatEvent:
    type: ChatWSEventType
    payload: dict[str, Any] | None = None
    message_id: str | None = None


class Emitter(Protocol):
    async def emit(self, event: ChatEvent) -> None: ...


@dataclass
class CollectingEmitter:
    """Keeps every event in order; used by the HTTP adapter and by tests."""

    events: list[ChatEvent] = field(default_factory=list)

    async def emit(self, event: ChatEvent) -> None:
        self.events.append(event)


class ActivityStepEmitter:
    """Builds today's ``activity.step.update`` payloads (the step ``sequence`` is the UI order)."""

    def __init__(self, emitter: Emitter) -> None:
        self._emitter = emitter
        self._step_seq = 0

    async def emit_step(
        self,
        step_key: str,
        label: str,
        state: str,
        detail: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        if state in ("running", "pending"):
            self._step_seq += 1
        await self._emitter.emit(
            ChatEvent(
                type="activity.step.update",
                payload={
                    "step_key": step_key,
                    "sequence": self._step_seq,
                    "label": label,
                    "state": state,
                    "detail": detail,
                    "duration_ms": duration_ms,
                },
            )
        )


# -- streaming events (R05-03, contract 4.2.6) -------------------------------------------
# Deltas and replaces carry text only; citations are presented with generation.final.


def generation_started_event(mode: str) -> ChatEvent:
    return ChatEvent(type="generation.started", payload={"mode": mode})


def generation_delta_event(text: str) -> ChatEvent:
    return ChatEvent(type="generation.delta", payload={"text": text})


def generation_replace_event(text: str, reason: str, message_id: str | None) -> ChatEvent:
    return ChatEvent(
        type="generation.replace",
        payload={"text": text, "reason": reason},
        message_id=message_id,
    )


def generation_final_event(payload: dict[str, Any], message_id: str | None) -> ChatEvent:
    return ChatEvent(type="generation.final", payload=payload, message_id=message_id)


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'s' if count != 1 else ''}"
