"""Prometheus counter for signing-key rotation (R08-11).

``APP_AUTH_SECRET_PREVIOUS`` keeps tokens signed before a rotation valid while they expire.
This counter shows how many verifications still need the previous key, so operators know
when the previous key can be removed (the counter stops growing). Labels are fixed values.
"""

from __future__ import annotations

from typing import Literal

from prometheus_client import Counter

from app.core.metrics import is_metrics_enabled, registry

TokenKind = Literal["access", "refresh", "bot_oauth_state"]

AUTH_TOKEN_VERIFIED_BY_PREVIOUS_KEY_TOTAL = Counter(
    "rudix_auth_token_verified_by_previous_key",
    "Signed values (tokens, OAuth state) verified with APP_AUTH_SECRET_PREVIOUS, by kind",
    ["kind"],
    registry=registry,
)


def record_verified_by_previous_key(kind: TokenKind) -> None:
    if not is_metrics_enabled():
        return
    AUTH_TOKEN_VERIFIED_BY_PREVIOUS_KEY_TOTAL.labels(kind=kind).inc()
