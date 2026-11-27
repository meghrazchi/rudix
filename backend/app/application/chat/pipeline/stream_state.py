"""Streaming state of one chat run (R05-03).

``mode`` is set when ``generation.started`` is sent: ``live`` forwards answer text as the
model writes it, ``buffered`` sends only the verified text after citation validation.
``streamed`` holds the text the client has seen since the last ``generation.replace``; the
final event compares it with the authoritative answer. ``progress`` keeps every provider
attempt so a cancelled run can record partial usage.
"""

from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal

from app.domains.chat.services.answer_stream import StreamProgress

StreamMode = Literal["live", "buffered"]
ReplaceReason = Literal["verification", "policy", "retry", "fallback", "normalisation"]

# Transports whose clients receive the events; TTFT is observed for these only.
STREAMING_TRANSPORTS = frozenset({"ws", "sse"})


@dataclass
class StreamState:
    started_at: float = field(default_factory=perf_counter)
    mode: StreamMode | None = None
    streamed: list[str] = field(default_factory=list)
    ttft_observed: bool = False
    # The answer as generation left it (after not-found mapping), before verification.
    answer_after_generation: str | None = None
    progress: StreamProgress = field(default_factory=StreamProgress)
    final_emitted: bool = False

    @property
    def streamed_text(self) -> str:
        return "".join(self.streamed)
