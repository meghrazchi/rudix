"""Prometheus metrics for the chat WebSocket connection limit (R08-03).

Registered on the shared registry of ``app.core.metrics``. Labels are fixed values, never
ids or request data:

- ``backend``: ``memory`` or ``redis`` (``WS_CHAT_CONNECTION_LIMIT_BACKEND``);
- ``outcome``: ``accepted`` (a slot was taken), ``rejected`` (limit reached, or Redis
  failed with ``RATE_LIMIT_REDIS_FAILURE_MODE=closed``), ``fallback`` (Redis failed in open
  mode and the connection was counted in process), ``lease_lost`` (a heartbeat refresh
  found the connection's lease gone).
"""

from __future__ import annotations

from typing import Literal

from prometheus_client import Counter

from app.core.metrics import is_metrics_enabled, registry

WsLimitOutcome = Literal["accepted", "rejected", "fallback", "lease_lost"]

CHAT_WS_CONNECTION_LIMIT_TOTAL = Counter(
    "rudix_chat_ws_connection_limit_total",
    "Chat WebSocket connection-limit decisions by backend and outcome",
    ["backend", "outcome"],
    registry=registry,
)


def record_ws_connection_limit(backend: str, outcome: WsLimitOutcome) -> None:
    if not is_metrics_enabled():
        return
    CHAT_WS_CONNECTION_LIMIT_TOTAL.labels(backend=backend, outcome=outcome).inc()
