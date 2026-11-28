"""Event-loop lag monitor (R04-11).

A background task sleeps for a short interval and measures how late it wakes up.
Any blocking call on the loop shows up as drift, exported as a Prometheus gauge
(worst lag in the current rolling window) and a histogram of every tick.
"""

from __future__ import annotations

import asyncio
import contextlib

from prometheus_client import Gauge, Histogram

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import registry

logger = get_logger("core.loop_lag")

EVENT_LOOP_LAG_SECONDS = Gauge(
    "rudix_event_loop_lag_seconds",
    "Worst event-loop scheduling lag in the current rolling window (seconds)",
    registry=registry,
    multiprocess_mode="livemax",
)
EVENT_LOOP_LAG_SECONDS_HIST = Histogram(
    "rudix_event_loop_lag_seconds_hist",
    "Event-loop scheduling lag per monitor tick in seconds",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=registry,
)


# The gauge holds the worst lag of a rolling window so one spike does not pin it forever.
# Keep the window at or above the Prometheus scrape interval.
DEFAULT_GAUGE_WINDOW_SECONDS = 30.0


class LoopLagMonitor:
    def __init__(
        self, interval_ms: int = 50, gauge_window_seconds: float = DEFAULT_GAUGE_WINDOW_SECONDS
    ) -> None:
        self._interval = interval_ms / 1000.0
        self._gauge_window = gauge_window_seconds
        self._max_lag = 0.0
        self._window_max = 0.0
        self._task: asyncio.Task[None] | None = None

    @property
    def max_lag_seconds(self) -> float:
        return self._max_lag

    def reset(self) -> float:
        """Return the worst lag since the last reset and start a new window."""
        value, self._max_lag = self._max_lag, 0.0
        return value

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @property
    def window_max_lag_seconds(self) -> float:
        """Worst lag in the current gauge window (the value exported as the gauge)."""
        return self._window_max

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        window_ends = loop.time() + self._gauge_window
        while True:
            expected = loop.time() + self._interval
            await asyncio.sleep(self._interval)
            now = loop.time()
            if now >= window_ends:
                self._window_max = 0.0
                window_ends = now + self._gauge_window
            lag = max(0.0, now - expected)
            self._max_lag = max(self._max_lag, lag)
            self._window_max = max(self._window_max, lag)
            EVENT_LOOP_LAG_SECONDS.set(self._window_max)
            EVENT_LOOP_LAG_SECONDS_HIST.observe(lag)


_monitor: LoopLagMonitor | None = None


def start_loop_lag_monitor() -> LoopLagMonitor | None:
    global _monitor
    if not settings.loop_lag_monitor_enabled:
        return None
    if _monitor is None:
        _monitor = LoopLagMonitor(settings.loop_lag_monitor_interval_ms)
    _monitor.start()
    logger.info("loop_lag.started", interval_ms=settings.loop_lag_monitor_interval_ms)
    return _monitor


async def stop_loop_lag_monitor() -> None:
    global _monitor
    monitor, _monitor = _monitor, None
    if monitor is not None:
        await monitor.stop()
