"""Prometheus metrics for browser session cookies (R07-09).

Kept out of ``app/core/metrics.py`` so release packages do not collide on that file; the
counters register on the shared registry and are exported by ``GET /metrics``.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter

from app.core.metrics import is_metrics_enabled, registry

logger = logging.getLogger("observability.metrics")

AUTH_CSRF_ORIGIN_REJECTIONS_TOTAL = Counter(
    "rudix_auth_csrf_origin_rejections_total",
    "Cookie-authenticated auth requests rejected by the Origin check (SameSite=None only)",
    ["endpoint", "reason"],
    registry=registry,
)


def record_csrf_origin_rejection(endpoint: str, reason: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        AUTH_CSRF_ORIGIN_REJECTIONS_TOTAL.labels(endpoint=endpoint, reason=reason).inc()
    except Exception as exc:  # pragma: no cover - metrics must never break a request
        logger.debug("metrics.record_csrf_origin_rejection_failed: %s", exc)
