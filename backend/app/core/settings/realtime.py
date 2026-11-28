"""Per-user realtime event stream settings (R07-07).

``GET /events/stream`` is off by default; with it off nothing is published and the frontend
keeps polling. Redis holds one channel, one bounded replay buffer, and one sequence counter
per organisation, plus a connection counter per user.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RealtimeSettings(BaseModel):
    realtime_events_enabled: bool = False
    # Replay buffer: how long events stay after the last write, and how many are kept.
    realtime_buffer_ttl_seconds: int = Field(default=120, ge=1, le=86_400)
    realtime_buffer_max_events: int = Field(default=500, ge=1, le=100_000)
    # A ``: keep-alive`` comment after this many idle seconds.
    realtime_stream_keepalive_seconds: int = Field(default=15, ge=1, le=300)
    # The stream ends after this long, so role changes and token expiry apply on reconnect.
    realtime_stream_max_seconds: int = Field(default=300, ge=1, le=3_600)
    realtime_max_connections_per_user: int = Field(default=5, ge=1, le=100)
