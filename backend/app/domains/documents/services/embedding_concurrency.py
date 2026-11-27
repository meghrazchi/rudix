"""Bounded concurrency and a shared provider pause for embedding batches (R06-06)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

# A provider asking for a longer pause than this is capped; the retry loop's own backoff
# and attempt limit still apply afterwards.
MAX_PAUSE_SECONDS = 60.0


class ProviderPauseGate:
    """Every batch waits here before calling the provider.

    A ``ProviderQuotaExceededError`` carrying a retry-after pauses all batches that share
    the gate until that deadline, instead of each batch hitting the limit on its own. The
    gate keeps a monotonic deadline rather than an ``asyncio.Event`` because the service
    that owns it outlives event loops (worker loop, test loops); waiting is a plain
    ``asyncio.sleep`` on whichever loop is running.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._resume_at = 0.0
        self.pauses = 0

    def pause(self, seconds: float) -> float:
        """Pause for ``seconds`` (capped); returns the applied pause."""
        applied = max(0.0, min(float(seconds), MAX_PAUSE_SECONDS))
        self._resume_at = max(self._resume_at, self._clock() + applied)
        self.pauses += 1
        return applied

    def remaining(self) -> float:
        return max(0.0, self._resume_at - self._clock())

    async def wait(self) -> None:
        while (delay := self.remaining()) > 0:
            await asyncio.sleep(delay)


async def run_bounded[T](factories: list[Callable[[], Awaitable[T]]], limit: int) -> list[T]:
    """Run the factories with at most ``limit`` at a time; results keep input order.

    ``limit`` 1 runs them one after another (the behaviour before R06-06). On the first
    failure the others are cancelled and that failure is raised.
    """
    if limit <= 1 or len(factories) <= 1:
        return [await factory() for factory in factories]
    semaphore = asyncio.Semaphore(limit)

    async def _one(factory: Callable[[], Awaitable[T]]) -> T:
        async with semaphore:
            return await factory()

    tasks = [asyncio.ensure_future(_one(factory)) for factory in factories]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
