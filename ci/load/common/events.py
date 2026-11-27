"""Custom Locust request events for timings that are not a single HTTP call."""

from __future__ import annotations

import time
from typing import Any


class ScenarioFailure(Exception):
    """A failed custom event; the message is a safe code, never response content."""


def elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def fire(
    environment: Any,
    *,
    request_type: str,
    name: str,
    started: float,
    exception: BaseException | None = None,
    response_length: int = 0,
) -> None:
    """Report a custom timing so it appears in Locust stats and ``--csv`` output."""
    environment.events.request.fire(
        request_type=request_type,
        name=name,
        response_time=elapsed_ms(started),
        response_length=response_length,
        exception=exception,
        context={},
    )
