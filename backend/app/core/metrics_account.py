"""Prometheus metrics for single-use account tokens (0.9.0, S1).

Kept out of ``app/core/metrics.py`` so release packages do not collide on that file; the
counters register on the shared registry and are exported by ``GET /metrics``. Labels are a
fixed set: the token purpose and an outcome, never a user, organisation, or token value.
"""

from __future__ import annotations

import logging
from typing import Literal

from prometheus_client import Counter

from app.core.metrics import is_metrics_enabled, registry

logger = logging.getLogger("observability.metrics")

OneTimeTokenOutcome = Literal[
    "issued",
    "duplicate",
    "consumed",
    "rejected",
    "failed_attempt",
    "revoked",
    "purged",
]

AUTH_ONE_TIME_TOKENS_TOTAL = Counter(
    "rudix_auth_one_time_tokens_total",
    "Single-use account token operations by purpose and outcome (purged: purpose 'all')",
    ["purpose", "outcome"],
    registry=registry,
)


def record_one_time_token(purpose: str, outcome: OneTimeTokenOutcome, amount: int = 1) -> None:
    if not is_metrics_enabled() or amount <= 0:
        return
    try:
        AUTH_ONE_TIME_TOKENS_TOTAL.labels(purpose=purpose, outcome=outcome).inc(amount)
    except Exception as exc:  # pragma: no cover - metrics must never break a request
        logger.debug("metrics.record_one_time_token_failed: %s", exc)
