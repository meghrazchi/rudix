from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_worker_loop: asyncio.AbstractEventLoop | None = None


def get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    loop = get_worker_loop()
    return loop.run_until_complete(coro)


def reset_worker_loop_after_fork() -> None:
    """Forget an event loop inherited from the parent process without closing it.

    The parent keeps using its loop (and the selector it owns); the child builds its own on
    the next ``run_async``.
    """
    global _worker_loop
    _worker_loop = None
