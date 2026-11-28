"""Prometheus metrics for first-party browser Web Vitals (R07-11).

Registered on the shared registry of ``app.core.metrics``. Route labels are bounded:
a process-local set keeps at most ``web_vitals_max_routes`` distinct values and every
further route is reported as ``"other"``, so a client cannot grow label cardinality.
"""

from __future__ import annotations

import threading

from prometheus_client import Counter, Histogram

from app.core.config import settings
from app.core.metrics import registry

OVERFLOW_ROUTE = "other"

WEB_VITALS_VALUE_MS = Histogram(
    "rudix_web_vitals_value_ms",
    "Browser Web Vitals timings in milliseconds (LCP, INP, FCP, TTFB) by route pattern",
    ["metric", "route"],
    buckets=(
        50,
        100,
        200,
        400,
        800,
        1200,
        1800,
        2500,
        3500,
        5000,
        8000,
        12000,
        20000,
        60000,
    ),
    registry=registry,
)

WEB_VITALS_CLS = Histogram(
    "rudix_web_vitals_cls",
    "Browser Cumulative Layout Shift (unitless) by route pattern",
    ["route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.15, 0.25, 0.5, 1.0, 2.5, 10.0),
    registry=registry,
)

WEB_VITALS_SAMPLES_TOTAL = Counter(
    "rudix_web_vitals_samples_total",
    "Web Vitals samples received by metric and outcome (accepted, rejected, rate_limited)",
    ["metric", "outcome"],
    registry=registry,
)

_known_routes: set[str] = set()
_routes_lock = threading.Lock()


def bounded_route(route: str) -> str:
    """Return ``route`` while the label budget allows it, else ``"other"``."""
    with _routes_lock:
        if route in _known_routes:
            return route
        if len(_known_routes) < settings.web_vitals_max_routes:
            _known_routes.add(route)
            return route
    return OVERFLOW_ROUTE


def reset_known_routes_for_testing() -> None:
    with _routes_lock:
        _known_routes.clear()


def record_web_vital(*, name: str, value: float, route: str) -> None:
    """Observe one accepted sample."""
    label = bounded_route(route)
    if name == "CLS":
        WEB_VITALS_CLS.labels(route=label).observe(value)
    else:
        WEB_VITALS_VALUE_MS.labels(metric=name, route=label).observe(value)
    WEB_VITALS_SAMPLES_TOTAL.labels(metric=name, outcome="accepted").inc()


def record_web_vitals_outcome(*, names: list[str], outcome: str) -> None:
    """Count samples that were not observed (rejected, rate_limited)."""
    for name in names:
        WEB_VITALS_SAMPLES_TOTAL.labels(metric=name, outcome=outcome).inc()
